from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("netbox_bmc", "0005_device_firmware_cf"),
    ]

    operations = [
        migrations.AddField(
            model_name="bmcendpoint",
            name="detected_serial",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
