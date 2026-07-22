from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("netbox_bmc", "0010_bmcendpoint_manager_health_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="bmcendpoint",
            name="use_netbox_secrets",
            field=models.BooleanField(default=True),
        ),
    ]
