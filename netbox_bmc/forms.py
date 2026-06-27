from dcim.models import Device
from django import forms
from ipam.models import IPAddress
from netbox.forms import NetBoxModelForm
from utilities.forms.fields import DynamicModelChoiceField

from .models import BMCEndpoint


class BMCEndpointForm(NetBoxModelForm):
    device = DynamicModelChoiceField(queryset=Device.objects.all())
    ip_address = DynamicModelChoiceField(
        queryset=IPAddress.objects.all(),
        query_params={"device_id": "$device"},
        label="IP Address",
        help_text="Device に割り当てられた BMC 管理 IP を選択",
    )
    password = forms.CharField(widget=forms.PasswordInput(render_value=True))

    class Meta:
        model = BMCEndpoint
        fields = (
            "device", "ip_address", "port", "protocol",
            "username", "password", "verify_ssl", "tags",
        )
