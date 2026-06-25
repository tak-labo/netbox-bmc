from django.db import migrations


def create_custom_field(apps, schema_editor):
    try:
        ContentType = apps.get_model("contenttypes", "ContentType")
        CustomField = apps.get_model("extras", "CustomField")

        ct = ContentType.objects.filter(
            app_label="dcim", model="inventoryitem"
        ).first()
        if ct is None:
            return

        cf, created = CustomField.objects.get_or_create(
            name="bmc_redfish_path",
            defaults={
                "type": "url",
                "label": "Redfish Path",
                "group_name": "BMC",
                "description": "Redfish API path for this component (managed by netbox-bmc)",
                "ui_editable": "hidden",
            },
        )
        if created or not cf.object_types.filter(pk=ct.pk).exists():
            cf.object_types.add(ct)
    except Exception:
        pass


def remove_custom_field(apps, schema_editor):
    try:
        CustomField = apps.get_model("extras", "CustomField")
        CustomField.objects.filter(name="bmc_redfish_path").delete()
    except Exception:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_bmc", "0002_add_jobs_feature"),
    ]

    operations = [
        migrations.RunPython(create_custom_field, remove_custom_field),
    ]
