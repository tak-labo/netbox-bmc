from django.db import models
from django.urls import reverse
from netbox.models import NetBoxModel
from netbox.models.features import JobsMixin


class Protocol(models.TextChoices):
    AUTO = "auto", "Auto-detect"
    REDFISH = "redfish", "Redfish"
    WSMAN = "wsman", "WS-MAN (Intel AMT)"
    IPMI = "ipmi", "IPMI"


class BMCEndpoint(JobsMixin, NetBoxModel):
    """デバイスごとの OOB 管理エンドポイント。"""
    device = models.OneToOneField(
        to="dcim.Device", on_delete=models.CASCADE, related_name="bmc_endpoint",
    )
    address = models.CharField(max_length=255, help_text="BMC の IP / FQDN")
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
        help_text="Fallback when netbox-secrets is not available",
    )
    password = models.CharField(
        max_length=255, blank=True,
        help_text="Fallback when netbox-secrets is not available (plaintext)",
    )

    # 同期ステータス
    detected_vendor = models.CharField(max_length=64, blank=True)
    detected_protocol = models.CharField(max_length=16, blank=True)
    detected_serial = models.CharField(max_length=255, blank=True)
    last_sync = models.DateTimeField(blank=True, null=True)
    last_sync_status = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("device",)
        verbose_name = "BMC endpoint"

    def __str__(self):
        return f"{self.device} ({self.address})"

    def get_absolute_url(self):
        return reverse("plugins:netbox_bmc:bmcendpoint", args=[self.pk])

    def get_driver(self, request=None):
        """
        BMC ドライバを生成して返す。

        request を渡すと netbox-secrets のセッションキーで認証情報を復号する。
        None の場合はサービスアカウント秘密鍵またはフォールバック平文を使用。
        """
        from .credentials import get_credential
        from .drivers.base import detect_and_build

        cred = get_credential(self, request=request)
        return detect_and_build(
            self.address, cred.username, cred.password,
            protocol=self.protocol, port=self.port,
            verify_ssl=self.verify_ssl,
        )
