import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("dcim", "0001_squashed"),
        ("extras", "0001_squashed"),
    ]

    operations = [
        migrations.CreateModel(
            name="BMCEndpoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("last_updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "custom_field_data",
                    models.JSONField(blank=True, default=dict, encoder=None),
                ),
                (
                    "device",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bmc_endpoint",
                        to="dcim.device",
                    ),
                ),
                ("address", models.CharField(help_text="BMC の IP / FQDN", max_length=255)),
                ("port", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "protocol",
                    models.CharField(
                        choices=[("auto", "Auto-detect"), ("redfish", "Redfish"), ("ipmi", "IPMI")],
                        default="auto",
                        max_length=16,
                    ),
                ),
                ("verify_ssl", models.BooleanField(default=False)),
                (
                    "username",
                    models.CharField(
                        blank=True,
                        help_text="Fallback when netbox-secrets is not available",
                        max_length=128,
                    ),
                ),
                (
                    "password",
                    models.CharField(
                        blank=True,
                        help_text="Fallback when netbox-secrets is not available (plaintext)",
                        max_length=255,
                    ),
                ),
                ("detected_vendor", models.CharField(blank=True, max_length=64)),
                ("detected_protocol", models.CharField(blank=True, max_length=16)),
                ("last_sync", models.DateTimeField(blank=True, null=True)),
                ("last_sync_status", models.CharField(blank=True, max_length=255)),
            ],
            options={
                "verbose_name": "BMC endpoint",
                "ordering": ("device",),
            },
        ),
        migrations.AddField(
            model_name="bmcendpoint",
            name="tags",
            field=models.ManyToManyField(blank=True, related_name="+", to="extras.tag"),
        ),
    ]
