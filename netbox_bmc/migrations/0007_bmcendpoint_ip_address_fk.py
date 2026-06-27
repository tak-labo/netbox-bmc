import django.db.models.deletion
from django.db import migrations, models


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
