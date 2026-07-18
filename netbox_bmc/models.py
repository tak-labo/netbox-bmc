from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from netbox.models import NetBoxModel
from netbox.models.features import JobsMixin


class Protocol(models.TextChoices):
    AUTO = "auto", _("Auto-detect")
    REDFISH = "redfish", _("Redfish")
    WSMAN = "wsman", _("WS-MAN (Intel AMT)")
    IPMI = "ipmi", _("IPMI")


class BMCEndpoint(JobsMixin, NetBoxModel):
    """デバイスごとの OOB 管理エンドポイント。"""
    device = models.OneToOneField(
        to="dcim.Device", on_delete=models.CASCADE, related_name="bmc_endpoint",
    )
    ip_address = models.ForeignKey(
        to="ipam.IPAddress", on_delete=models.PROTECT,
        related_name="bmc_endpoints",
        help_text=_("BMC management IP assigned to the Device"),
    )
    port = models.PositiveIntegerField(blank=True, null=True)
    protocol = models.CharField(
        max_length=16, choices=Protocol.choices, default=Protocol.AUTO,
    )
    verify_ssl = models.BooleanField(default=False)

    # ---
    # 認証情報フィールド (平文フォールバック用)
    # netbox-secrets が利用可能な場合は使われない。
    # netbox-secrets の Secret は Device に直接紐づくため、
    # BMCEndpoint にはポインタを持たない (Device の pk で検索する)。
    # ---
    username = models.CharField(
        max_length=128, blank=True,
        help_text=_("Fallback when netbox-secrets is not available"),
    )
    password = models.CharField(
        max_length=255, blank=True,
        help_text=_("Fallback when netbox-secrets is not available (plaintext)"),
    )

    # 同期ステータス
    detected_vendor = models.CharField(max_length=64, blank=True)
    detected_protocol = models.CharField(max_length=16, blank=True)
    detected_serial = models.CharField(max_length=255, blank=True)
    last_sync = models.DateTimeField(blank=True, null=True)
    last_sync_status = models.CharField(max_length=255, blank=True)

    # BMC 自身のネットワーク設定 (NetworkSyncJob / ScheduledNetworkSyncJob が更新)
    # inventory.BmcNetworkInterface のリストを dataclasses.asdict() でシリアライズして保存
    network_interfaces = models.JSONField(default=list, blank=True)
    network_last_sync = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("device",)
        verbose_name = "BMC endpoint"

    def __str__(self):
        return f"{self.device} ({self.ip_address})"

    def get_absolute_url(self):
        return reverse("plugins:netbox_bmc:bmcendpoint", args=[self.pk])

    def _bmc_host(self, use_dns=False):
        if use_dns and self.ip_address.dns_name:
            host = self.ip_address.dns_name
        else:
            host = str(self.ip_address.address.ip)
        return f"{host}:{self.port}" if self.port else host

    @property
    def dns_name(self):
        return self.ip_address.dns_name or ""

    @property
    def web_gui_url(self):
        return f"https://{self._bmc_host()}/"

    @property
    def web_gui_url_dns(self):
        return f"https://{self._bmc_host(use_dns=True)}/" if self.ip_address.dns_name else None

    def get_driver(self, request=None):
        """
        BMC ドライバを生成して返す。

        request を渡すと netbox-secrets のセッションキーで認証情報を復号する。
        None の場合はサービスアカウント秘密鍵またはフォールバック平文を使用。
        """
        from .credentials import get_credential
        from .drivers.base import detect_and_build

        cred = get_credential(self, request=request)
        # IPAddress.address is a netaddr.IPNetwork; .ip gives the host part
        address = str(self.ip_address.address.ip)
        return detect_and_build(
            address, cred.username, cred.password,
            protocol=self.protocol, port=self.port,
            verify_ssl=self.verify_ssl,
        )
