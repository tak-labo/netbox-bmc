from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("netbox_bmc", "0008_bmcendpoint_network_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="bmcendpoint",
            name="sensors",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="sensors_last_sync",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="event_log",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="event_log_last_sync",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
