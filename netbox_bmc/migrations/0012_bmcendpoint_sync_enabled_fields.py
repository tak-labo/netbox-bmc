from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("netbox_bmc", "0011_bmcendpoint_use_netbox_secrets"),
    ]

    operations = [
        migrations.AddField(
            model_name="bmcendpoint",
            name="network_sync_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Sync this endpoint's network configuration in the background. "
                          "When disabled, the Network card is hidden and the manual sync "
                          "button and scheduled bulk sync both skip this endpoint.",
            ),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="sensors_sync_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Sync this endpoint's sensor telemetry in the background. When "
                          "disabled, the Sensors card is hidden and the manual sync button "
                          "and scheduled bulk sync both skip this endpoint.",
            ),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="event_log_sync_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Sync this endpoint's System Event Log in the background. When "
                          "disabled, the Event Log card is hidden and the manual sync "
                          "button and scheduled bulk sync both skip this endpoint.",
            ),
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="manager_health_sync_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Sync this endpoint's BMC health status in the background. When "
                          "disabled, the Manager Health sync button and its fields on the "
                          "Sync Status card are hidden, and the manual sync button and "
                          "scheduled bulk sync both skip this endpoint.",
            ),
        ),
    ]
