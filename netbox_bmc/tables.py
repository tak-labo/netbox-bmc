import django_tables2 as tables
from netbox.tables import NetBoxTable

from .models import BMCEndpoint


class BMCEndpointTable(NetBoxTable):
    device = tables.Column(linkify=True)
    ip_address = tables.Column(linkify=True, verbose_name="IP Address")
    protocol = tables.Column()
    detected_vendor = tables.Column(verbose_name="Vendor")
    last_sync = tables.DateTimeColumn()
    last_sync_status = tables.Column(verbose_name="Last Sync Status")

    class Meta(NetBoxTable.Meta):
        model = BMCEndpoint
        fields = (
            "pk", "device", "ip_address", "port", "protocol",
            "detected_vendor", "detected_protocol",
            "last_sync", "last_sync_status",
        )
        default_columns = (
            "device", "ip_address", "protocol",
            "detected_vendor", "last_sync", "last_sync_status",
        )
