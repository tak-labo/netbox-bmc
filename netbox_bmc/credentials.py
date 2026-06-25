"""
netbox-secrets からBMC認証情報を取得するヘルパー。

【復号の経路】
  バックグラウンドジョブ (InventorySyncJob / ScheduledInventorySyncJob):
    request なし → PLUGINS_CONFIG の service_private_key_path に
    置いたサービスアカウントの RSA 秘密鍵 (PEM) で UserKey を復号し
    master_key を取得する。

  request 引数経路は将来的な REST API 同期実行用に残してあるが、
  ジョブ kwargs を介してセッションキーを渡すと Job レコードに平文で
  保存されてしまうため、現状の UI トリガーでは使用しない。

【Secretのレイアウト規約】
  - SecretRole slug : bmc-credentials
  - Secret.name    : BMC username (非暗号化フィールド)
  - Secret.plaintext: BMC password (RSA暗号化)
  - assigned_object: Device (当該 BMCEndpoint の device)

【フォールバック動作】
  netbox-secrets が未インストールの場合は BMCEndpoint.username/password の
  平文フィールドにフォールバックする (後方互換)。
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.contenttypes.models import ContentType

if TYPE_CHECKING:
    from django.http import HttpRequest

    from .models import BMCEndpoint

logger = logging.getLogger("netbox_bmc.credentials")

SECRET_ROLE_SLUG = "bmc-credentials"


@dataclass
class Credential:
    username: str
    password: str
    source: str  # "netbox_secrets" | "plaintext_fallback"


def get_credential(endpoint: BMCEndpoint,
                   request: HttpRequest | None = None) -> Credential:
    """
    BMCEndpoint に紐づく認証情報を取得して返す。

    netbox-secrets が使用可能な場合:
      - request が渡された場合はセッションキーで復号
      - request=None の場合はサービスアカウント秘密鍵で復号

    どちらも失敗した場合 / netbox-secrets 未インストールの場合:
      - endpoint.username / endpoint.password を返す
    """
    try:
        return _get_from_secrets(endpoint, request)
    except _SecretsUnavailable:
        logger.debug("netbox-secrets unavailable, using plaintext fields")
    except _SecretNotFound:
        logger.debug("No bmc-credentials secret for device %s, using plaintext fields",
                     endpoint.device)
    except Exception as e:
        # netbox-secrets が利用可能なのに復号に失敗した場合は警告ではなく
        # error レベルで残す (運用上、無音で平文に落ちると気付きにくい)。
        logger.error("Failed to decrypt secret for %s: %s, using plaintext fields",
                     endpoint.device, e)

    # フォールバック
    return Credential(
        username=endpoint.username,
        password=endpoint.password,
        source="plaintext_fallback",
    )


# ---------------------------------------------------------------------------
# 内部実装
# ---------------------------------------------------------------------------

class _SecretsUnavailable(Exception):
    pass


class _SecretNotFound(Exception):
    pass


def _get_from_secrets(endpoint: BMCEndpoint,
                      request: HttpRequest | None) -> Credential:
    try:
        from netbox_secrets.models import Secret, SecretRole
    except ImportError:
        raise _SecretsUnavailable from None

    device = endpoint.device
    device_ct = ContentType.objects.get_for_model(device)

    role_qs = SecretRole.objects.filter(slug=SECRET_ROLE_SLUG)
    if not role_qs.exists():
        raise _SecretNotFound(f"SecretRole '{SECRET_ROLE_SLUG}' not found")

    secret_qs = Secret.objects.filter(
        role__in=role_qs,
        assigned_object_type=device_ct,
        assigned_object_id=device.pk,
    )
    if not secret_qs.exists():
        raise _SecretNotFound

    secret = secret_qs.first()
    master_key = _resolve_master_key(request)
    secret.decrypt(master_key)

    if secret.plaintext is None:
        raise Exception("decrypt returned None — wrong key?")

    return Credential(
        username=secret.name,          # name フィールドがユーザー名
        password=secret.plaintext,
        source="netbox_secrets",
    )


def _resolve_master_key(request: HttpRequest | None) -> bytes:
    """
    master_key (bytes) を返す。

    request あり  → Cookie または X-Session-Key ヘッダからセッションキーを取得
    request なし  → サービスアカウント秘密鍵で復号
    """

    if request is not None:
        return _master_key_from_request(request)

    return _master_key_from_service_account()


def _master_key_from_request(request) -> bytes:
    from netbox_secrets.models import UserKey

    # X-Session-Key ヘッダ (API) or session_key Cookie (ブラウザ)
    session_key_b64 = (
        request.META.get("HTTP_X_SESSION_KEY")
        or request.COOKIES.get("session_key")
    )
    if not session_key_b64:
        raise Exception("No X-Session-Key header or session_key cookie in request")

    session_key = base64.b64decode(session_key_b64)
    try:
        uk = UserKey.objects.get(user=request.user)
    except UserKey.DoesNotExist as e:
        raise Exception(f"No UserKey found for user {request.user}") from e

    master_key = uk.get_master_key(session_key)
    if master_key is None:
        raise Exception("get_master_key returned None — session key may be expired")
    return master_key


def _master_key_from_service_account() -> bytes:
    """
    PLUGINS_CONFIG["netbox_bmc"]["service_account"] で指定された
    サービスアカウントの UserKey と RSA 秘密鍵ファイルで master_key を取得する。

    configuration.py での設定例:
        PLUGINS_CONFIG = {
            "netbox_bmc": {
                "service_account": "bmc-sync",          # NetBoxユーザー名
                "service_private_key_path": "/opt/netbox/bmc-sync.pem",
            }
        }
    """
    from netbox_secrets.models import UserKey

    plugin_cfg = settings.PLUGINS_CONFIG.get("netbox_bmc", {})
    account = plugin_cfg.get("service_account")
    key_path = plugin_cfg.get("service_private_key_path")

    if not account or not key_path:
        raise Exception(
            "service_account and service_private_key_path must be set in "
            "PLUGINS_CONFIG['netbox_bmc'] for background job decryption"
        )

    pem = Path(key_path).read_text()

    try:
        uk = UserKey.objects.get(user__username=account)
    except UserKey.DoesNotExist as e:
        raise Exception(f"No UserKey for service account '{account}'") from e

    # UserKey.get_master_key は秘密鍵PEM文字列を受け付ける
    master_key = uk.get_master_key(private_key=pem)
    if master_key is None:
        raise Exception(
            f"master_key is None for service account '{account}' — "
            "check that the private key matches the stored public key"
        )
    return master_key
