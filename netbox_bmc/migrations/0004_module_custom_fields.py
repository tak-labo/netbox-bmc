from django.db import migrations


def create_module_custom_fields(apps, schema_editor):
    try:
        ContentType = apps.get_model("contenttypes", "ContentType")
        CustomField = apps.get_model("extras", "CustomField")

        ct = ContentType.objects.filter(app_label="dcim", model="module").first()
        if ct is None:
            return

        # bmc_redfish_path: move from InventoryItem to Module
        cf_path, _ = CustomField.objects.get_or_create(
            name="bmc_redfish_path",
            defaults={
                "type": "url",
                "label": "Redfish Path",
                "group_name": "BMC",
                "description": "Redfish API path for this component (managed by netbox-bmc)",
                "ui_editable": "hidden",
            },
        )
        if not cf_path.object_types.filter(pk=ct.pk).exists():
            cf_path.object_types.add(ct)

        # Remove from InventoryItem if present
        inv_ct = ContentType.objects.filter(
            app_label="dcim", model="inventoryitem"
        ).first()
        if inv_ct:
            cf_path.object_types.remove(inv_ct)

        # bmc_firmware_version: new CF for Module
        cf_fw, _ = CustomField.objects.get_or_create(
            name="bmc_firmware_version",
            defaults={
                "type": "text",
                "label": "Firmware Version",
                "group_name": "BMC",
                "description": "Firmware version reported by BMC (managed by netbox-bmc)",
                "ui_editable": "hidden",
            },
        )
        if not cf_fw.object_types.filter(pk=ct.pk).exists():
            cf_fw.object_types.add(ct)
    except Exception:
        pass


def remove_module_custom_fields(apps, schema_editor):
    try:
        CustomField = apps.get_model("extras", "CustomField")
        CustomField.objects.filter(
            name__in=["bmc_firmware_version"]
        ).delete()
        # Restore bmc_redfish_path to InventoryItem (best effort)
        ContentType = apps.get_model("contenttypes", "ContentType")
        cf = CustomField.objects.filter(name="bmc_redfish_path").first()
        if cf:
            inv_ct = ContentType.objects.filter(
                app_label="dcim", model="inventoryitem"
            ).first()
            if inv_ct:
                cf.object_types.add(inv_ct)
    except Exception:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_bmc", "0003_inventoryitem_redfish_path_cf"),
    ]

    operations = [
        migrations.RunPython(
            create_module_custom_fields, remove_module_custom_fields
        ),
    ]
