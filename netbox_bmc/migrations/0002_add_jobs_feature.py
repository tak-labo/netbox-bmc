from django.db import migrations


def add_jobs_feature(apps, schema_editor):
    try:
        ObjectType = apps.get_model("core", "ObjectType")
        ot = ObjectType.objects.filter(app_label="netbox_bmc", model="bmcendpoint").first()
        if ot and "jobs" not in (ot.features or []):
            ot.features = list(ot.features or []) + ["jobs"]
            ot.save()
    except Exception:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_bmc", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_jobs_feature, migrations.RunPython.noop),
    ]
