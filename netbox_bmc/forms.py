from django import forms
from netbox.forms import NetBoxModelForm
from utilities.forms.fields import DynamicModelChoiceField
from dcim.models import Device

from .models import BMCEndpoint


class BMCEndpointForm(NetBoxModelForm):
    device = DynamicModelChoiceField(queryset=Device.objects.all())
    password = forms.CharField(widget=forms.PasswordInput(render_value=True))

    class Meta:
        model = BMCEndpoint
        fields = (
            "device", "address", "port", "protocol",
            "username", "password", "verify_ssl", "tags",
        )
