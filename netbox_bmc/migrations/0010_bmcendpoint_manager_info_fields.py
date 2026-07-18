from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("netbox_bmc", "0009_bmcendpoint_sensors_eventlog_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="bmcendpoint",
            name="manager_info",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="manager_info_last_sync",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
