from django.db import migrations


def add_device_firmware_cf(apps, schema_editor):
    try:
        ContentType = apps.get_model("contenttypes", "ContentType")
        CustomField = apps.get_model("extras", "CustomField")

        device_ct = ContentType.objects.filter(app_label="dcim", model="device").first()
        if device_ct is None:
            return

        cf, _ = CustomField.objects.get_or_create(
            name="bmc_firmware_inventory",
            defaults={
                "type": "json",
                "label": "Firmware Inventory",
                "group_name": "BMC",
                "description": "Firmware versions reported by BMC (managed by netbox-bmc)",
                "ui_editable": "hidden",
            },
        )
        if not cf.object_types.filter(pk=device_ct.pk).exists():
            cf.object_types.add(device_ct)

        # Remove bmc_firmware_version from Module (no longer used)
        module_ct = ContentType.objects.filter(app_label="dcim", model="module").first()
        if module_ct:
            cf_fw = CustomField.objects.filter(name="bmc_firmware_version").first()
            if cf_fw:
                cf_fw.object_types.remove(module_ct)
                if not cf_fw.object_types.exists():
                    cf_fw.delete()
    except Exception:
        pass


def remove_device_firmware_cf(apps, schema_editor):
    try:
        CustomField = apps.get_model("extras", "CustomField")
        CustomField.objects.filter(name="bmc_firmware_inventory").delete()
    except Exception:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_bmc", "0004_module_custom_fields"),
    ]

    operations = [
        migrations.RunPython(add_device_firmware_cf, remove_device_firmware_cf),
    ]
