from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("netbox_bmc", "0009_bmcendpoint_sensors_eventlog_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="bmcendpoint",
            name="detected_firmware_version",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="manager_health",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="manager_health_last_sync",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
