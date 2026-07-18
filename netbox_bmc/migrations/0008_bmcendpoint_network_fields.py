from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("netbox_bmc", "0007_bmcendpoint_ip_address_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="bmcendpoint",
            name="network_interfaces",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="network_last_sync",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
