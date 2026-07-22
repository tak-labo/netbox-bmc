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

    fieldsets_with_secrets = (
        FieldSet("device_role", "device", "ip_address", name=_("Device")),
        FieldSet("port", "protocol", "verify_ssl", name=_("Connection")),
        FieldSet("use_netbox_secrets", "username", "password", name=_("Credentials")),
        FieldSet("tags", name=_("Other")),
    )
    fieldsets_without_secrets = (
        FieldSet("device_role", "device", "ip_address", name=_("Device")),
        FieldSet("port", "protocol", "verify_ssl", name=_("Connection")),
        FieldSet("username", "password", name=_("Credentials")),
        FieldSet("tags", name=_("Other")),
    )
    fieldsets = fieldsets_with_secrets

    class Meta:
        model = BMCEndpoint
        fields = (
            "device", "ip_address", "port", "protocol",
            "use_netbox_secrets", "username", "password", "verify_ssl", "tags",
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
            self.fieldsets = self.fieldsets_without_secrets
