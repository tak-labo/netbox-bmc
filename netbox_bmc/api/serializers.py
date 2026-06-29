from netbox.api.serializers import NetBoxModelSerializer
from rest_framework import serializers

from ..models import BMCEndpoint


class BMCEndpointSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_bmc-api:bmcendpoint-detail",
    )
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = BMCEndpoint
        fields = (
            "id", "url", "display",
            "device", "ip_address", "port", "protocol", "verify_ssl",
            "username", "password",
            "detected_vendor", "detected_protocol",
            "last_sync", "last_sync_status",
            "tags", "custom_fields", "created", "last_updated",
        )
        brief_fields = ("id", "url", "display", "device", "ip_address")
