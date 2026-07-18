# netbox-secrets 連携ガイド

`netbox_bmc` は BMC の認証情報(username/password)を [netbox-secrets](https://github.com/Onemind-Services-LLC/netbox-secrets)
経由で管理できる。本書は導入手順と、実際に動作確認した手順を記す。

netbox-secrets が未インストール、またはデバイスに `bmc-credentials` ロールの Secret が
見つからない場合は `BMCEndpoint.username` / `password`(平文フィールド)に自動的に
フォールバックする。詳細な実装は `netbox_bmc/credentials.py` を参照。

## 前提: プラグインのインストール

`netbox-docker` 環境の場合、`Dockerfile-Plugins` に `netbox-secrets` の pip インストールが
含まれている必要がある(`netbox_bmc` / `netbox_pdu_control` のようなローカル editable
インストールとは別に、PyPI パッケージとして追加する)。

```dockerfile
RUN uv pip install --python /opt/netbox/venv/bin/python3 \
    -e /opt/netbox-plugins/netbox-pdu-control \
    -e /opt/netbox-plugins/netbox-bmc \
    -e /opt/netbox-plugins/netbox-thermal-view \
    netbox-secrets
```

`configuration/plugins.py` の `PLUGINS` に `netbox_secrets` を追加し、イメージを再ビルドする。
`PLUGINS` に追加しただけでパッケージ自体がインストールされていないと、NetBox 起動時に
`ImproperlyConfigured: Unable to import plugin netbox_secrets: Module not found` で
コンテナが落ちるので注意。

## 1. 管理者による初回セットアップ

**Secret Role の作成**: `Secrets` → `Secret Roles` → `Add` で、slug を
`bmc-credentials` にしたロールを作成する。`netbox_bmc/credentials.py` の
`SECRET_ROLE_SLUG` がこの値を固定で参照するため、slug は変更不可。

## 2. 各ユーザーの鍵登録(初回のみ、ユーザーごと)

netbox-secrets は公開鍵暗号方式(RSA)で「master_key」を保護する設計になっている。

1. RSA 鍵ペアを生成する(2048bit 以上)。手元の端末で生成し、秘密鍵はサーバーに送らない。
   - NetBox 側にも `GET /api/plugins/secrets/generate-rsa-keypair/` という鍵ペア生成
     エンドポイントがあるが、生成された秘密鍵はレスポンスで一度返るだけで保存されないため、
     本番運用では信頼できる自分の環境で生成する方が安全。
2. `Secrets` → `User Keys` → 自分の User Key 編集画面で公開鍵(PEM)を登録して保存する。
   - このとき、まだ誰もアクティブな User Key を持っていない場合は、サーバー側で
     ランダムな `master_key` が自動生成され、あなたの公開鍵で暗号化されて保存される
     (`UserKey.save()` の自動 activate ロジック)。これがシステム全体で共有される唯一の
     master_key になる。
   - 2人目以降のユーザーは、既にアクティブな管理者に `ActivateUserkeyView`
     (`Secrets` → `User Keys` → 対象ユーザー → `Activate`)経由で自分の公開鍵に対して
     同じ master_key を暗号化してもらう必要がある(自分の秘密鍵だけでは新規登録できない)。

## 3. Device への Secret 割り当て

対象 Device の Secrets タブから `Add Secret` する。

| フィールド | 値 |
|---|---|
| Role | `bmc-credentials` |
| Name | BMC のユーザー名(平文フィールド) |
| Plaintext | BMC のパスワード(RSA 暗号化されて保存) |

netbox_bmc 側の `BMCEndpoint.username` / `password`(平文フォールバック)は空欄のままでよい。

## 4. UI 操作時のセッションアンロック

Build Modules・電源操作など、`endpoint.get_driver(request=request)` を呼ぶ操作
(`BuildModulesView` / `PowerActionView` / `IdentifyActionView` / `PowerStatusView` /
`FetchRawView` / `ConnectivityTestView`)を実行するとき、暗号化された Secret を復号する
必要がある。netbox-secrets の Secret 詳細画面を開くと秘密鍵入力モーダルが表示され、
入力すると `POST /api/plugins/secrets/session-key/` にリクエストが飛び、
`netbox_secrets_sessionid` という Cookie がセットされる。これ以降はこの Cookie が
自動的に送信されるため、ブラウザセッション中(`LOGIN_TIMEOUT` 設定に依存)は
再入力不要になる。

netbox_bmc 側は `netbox_bmc/credentials.py` の `_master_key_from_request()` が
`netbox_secrets.utils.get_session_key(request)` で Cookie / `X-Session-Key` ヘッダ /
POST の `session_key` からセッションキーを取り出し、
`SessionKey.objects.get(userkey__user=request.user).get_master_key(session_key)`
で `master_key` を復号する。

## 5. バックグラウンドジョブ用のサービスアカウント

`NetworkSyncJob` などの `request` を持たないバックグラウンドジョブは、Cookie/セッションを
使えないため、専用のサービスアカウントで復号する。

1. サービスアカウント用の NetBox ユーザーを作成する。
2. そのユーザー専用の RSA 鍵ペアを生成する。
3. 管理者(既にアクティブな User Key を持つユーザー)がサービスアカウントの公開鍵に対して
   `ActivateUserkeyView` 経由で同じ master_key を activate する。
4. 秘密鍵ファイルをサーバー上の安全な場所(例: `/opt/netbox/bmc-sync.pem`、パーミッションを
   絞る)に配置する。
5. `configuration.py` に設定する:

```python
PLUGINS_CONFIG = {
    "netbox_bmc": {
        "service_account": "bmc-sync",
        "service_private_key_path": "/opt/netbox/bmc-sync.pem",
    },
}
```

これで `netbox_bmc/credentials.py:_master_key_from_service_account()` が
`UserKey.objects.get(user__username=service_account)` を取得し、
`UserKey.get_master_key(private_key=<pemファイルの内容>)` で `master_key` を復号する。

## 過去に見つかった不具合 (fixed)

`_master_key_from_request()` は当初、以下の2点が実際の netbox-secrets 実装と
食い違っており、常に復号に失敗して平文フィールドへ無言でフォールバックしていた
(`get_credential()` の広い `except Exception` が握りつぶすため、ログを見ないと
気付けない):

1. Cookie 名を `session_key` としていたが、正しくは `netbox_secrets_sessionid`
   (`netbox_secrets/constants.py` の `SESSION_COOKIE_NAME`)。
2. `UserKey.get_master_key(session_key)` を呼んでいたが、`UserKey.get_master_key()`
   は RSA 秘密鍵専用のメソッド(内部で `RSA.importKey(private_key)` を呼ぶ)。
   セッションキー(対称鍵)での復号は別モデルの
   `SessionKey.objects.get(userkey__user=request.user).get_master_key(session_key)`
   を使う必要がある。

修正は PR #57 で `SessionKey` モデル経由に書き換え済み。

## 動作検証手順 (このドキュメントの根拠)

以下の手順で実際に netbox-secrets 本体のコードを読み、`manage.py shell` 上で
一連のフローを実機相当で再現して検証した。

```python
from Crypto.PublicKey import RSA
from django.test import Client
from netbox_secrets.models import UserKey, SecretRole, Secret
from netbox_bmc.credentials import get_credential
import json

# 1. RSA鍵ペア生成 + UserKey登録(自動activate)
key = RSA.generate(2048)
priv_pem = key.export_key('PEM').decode()
pub_pem = key.publickey().export_key('PEM').decode()
uk = UserKey(user=some_user, public_key=pub_pem)
uk.save()
master_key = uk.get_master_key(priv_pem)

# 2. SecretRole + Secret 作成(Deviceに割り当て)
role, _ = SecretRole.objects.get_or_create(slug='bmc-credentials', defaults={'name': 'BMC Credentials'})
secret = Secret(assigned_object=device, role=role, name='someuser', plaintext='somepass')
secret.encrypt(master_key)
secret.save()

# 3. 実際のセッションキーAPIを叩いてCookieをセット(UIと同じ経路)
c = Client()
c.force_login(some_user)
c.post('/api/plugins/secrets/session-key/',
       data=json.dumps({'private_key': priv_pem}), content_type='application/json')

# 4. Cookie付きのrequestでget_credential()を呼び、正しく復号されることを確認
request = c.get('/plugins/bmc/endpoints/').wsgi_request
cred = get_credential(endpoint, request=request)
assert cred.source == "netbox_secrets"
assert cred.username == "someuser" and cred.password == "somepass"
```

バックグラウンドジョブ経路(`request=None`)も、サービスアカウント用ユーザーに対して
同様に `UserKey` を作成・activate し、`PLUGINS_CONFIG` を設定した状態で
`netbox_bmc.jobs._sync_manager_health(endpoint)` 等を直接呼び、
`source == "netbox_secrets"` で復号されることを確認済み。

いずれのテストも、検証後は作成した `Secret` / `SessionKey` / `UserKey` /
`SecretRole` / サービスアカウントユーザーを削除して後始末している。
