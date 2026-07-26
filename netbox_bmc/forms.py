from dcim.models import Device, DeviceRole
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from ipam.models import IPAddress
from netbox.forms import NetBoxModelForm
from utilities.forms.fields import DynamicModelChoiceField
from utilities.forms.rendering import FieldSet

from .models import BMCEndpoint


class BMCEndpointForm(NetBoxModelForm):
    device_role = DynamicModelChoiceField(
        queryset=DeviceRole.objects.all(),
        required=False,
        label=_("Device Role (filter)"),
        help_text=_("Filter the Device choices by Role"),
    )
    device = DynamicModelChoiceField(
        queryset=Device.objects.all(),
        query_params={"role_id": "$device_role"},
    )
    ip_address = DynamicModelChoiceField(
        queryset=IPAddress.objects.all(),
        query_params={"device_id": "$device"},
        label=_("IP Address"),
        help_text=_("Select the BMC management IP assigned to the Device"),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=True), required=False,
        help_text=_("Fallback when netbox-secrets is not available (plaintext)"),
    )

    fieldsets = (
        FieldSet("device_role", "device", "ip_address", name=_("Device")),
        FieldSet("port", "protocol", "verify_ssl", name=_("Connection")),
        FieldSet("use_netbox_secrets", "username", "password", name=_("Credentials")),
        FieldSet("network_sync_enabled", "sensors_sync_enabled", "event_log_sync_enabled",
                  "manager_health_sync_enabled", name=_("Sync Options")),
        FieldSet("tags", name=_("Other")),
    )

    class Meta:
        model = BMCEndpoint
        fields = (
            "device", "ip_address", "port", "protocol",
            "use_netbox_secrets", "username", "password", "verify_ssl",
            "network_sync_enabled", "sensors_sync_enabled", "event_log_sync_enabled",
            "manager_health_sync_enabled", "tags",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is None:
            plugin_cfg = settings.PLUGINS_CONFIG.get("netbox_bmc", {})
            self.fields["verify_ssl"].initial = plugin_cfg.get("default_verify_ssl", False)

        try:
            import netbox_secrets  # noqa: F401
        except ImportError:
            # netbox-secrets 未インストールの場合、このチェックボックスは無意味なので隠す
            # (use_netbox_secrets はモデル側で default=True のままDBには残るが、
            # netbox-secrets 自体が無い環境では credentials.get_credential() が
            # どのみち _SecretsUnavailable にフォールバックするため実害はない)。
            del self.fields["use_netbox_secrets"]
            # Credentials フィールドセットは常に fieldsets の3番目 (index 2) —
            # 上の class 属性定義の並びと対応させている。
            fieldsets = list(self.fieldsets)
            fieldsets[2] = FieldSet("username", "password", name=_("Credentials"))
            self.fieldsets = tuple(fieldsets)

        # プラグイン全体でグローバルに無効化されている同期種別のチェックボックスは
        # 意味がないのでフォームから隠す (グローバル無効時は endpoint 側の値に
        # 関わらず _sync_enabled() が常に False を返すため)。
        plugin_cfg = settings.PLUGINS_CONFIG.get("netbox_bmc", {})
        sync_kinds = ("network", "sensors", "event_log", "manager_health")
        hidden_kinds = [k for k in sync_kinds if not plugin_cfg.get(f"{k}_sync_enabled", True)]
        for kind in hidden_kinds:
            del self.fields[f"{kind}_sync_enabled"]
        if hidden_kinds:
            remaining = [f"{kind}_sync_enabled" for kind in sync_kinds if kind not in hidden_kinds]
            fieldsets = list(self.fieldsets)
            sync_options_index = next(
                i for i, fs in enumerate(fieldsets) if fs.name == _("Sync Options")
            )
            if remaining:
                fieldsets[sync_options_index] = FieldSet(*remaining, name=_("Sync Options"))
            else:
                del fieldsets[sync_options_index]
            self.fieldsets = tuple(fieldsets)
