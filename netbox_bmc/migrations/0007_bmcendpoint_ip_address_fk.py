import django.db.models.deletion
from django.db import migrations, models


def link_ip_addresses(apps, schema_editor):
    """Create/link ipam.IPAddress for endpoints that only have a plain address string.

    Without this step the final AlterField (NOT NULL) fails on any database
    that already contains BMCEndpoint rows.
    """
    BMCEndpoint = apps.get_model("netbox_bmc", "BMCEndpoint")
    IPAddress = apps.get_model("ipam", "IPAddress")
    for endpoint in BMCEndpoint.objects.filter(ip_address__isnull=True):
        raw = endpoint.address
        cidr = raw if "/" in raw else f"{raw}/32"
        ip = IPAddress.objects.filter(address__net_host=raw.split("/")[0]).first()
        if ip is None:
            ip = IPAddress.objects.create(address=cidr)
        endpoint.ip_address = ip
        endpoint.save(update_fields=["ip_address"])
    # Fire deferred FK triggers now; the following ALTER TABLE on
    # ipam_ipaddress-referencing constraints fails while they are pending.
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):
    dependencies = [
        ("ipam", "0001_squashed"),
        ("netbox_bmc", "0006_bmcendpoint_detected_serial"),
    ]

    operations = [
        migrations.AddField(
            model_name="bmcendpoint",
            name="ip_address",
            field=models.ForeignKey(
                blank=True,
                null=True,
                help_text="Device に割り当てられた BMC 管理 IP",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bmc_endpoints",
                to="ipam.ipaddress",
            ),
        ),
        migrations.RunPython(link_ip_addresses, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="bmcendpoint",
            name="address",
        ),
        migrations.AlterField(
            model_name="bmcendpoint",
            name="ip_address",
            field=models.ForeignKey(
                help_text="Device に割り当てられた BMC 管理 IP",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bmc_endpoints",
                to="ipam.ipaddress",
            ),
        ),
    ]
