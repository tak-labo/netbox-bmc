"""
Module 同期エンジン。

InventoryResult (中間表現) → Module / ModuleBay / ModuleType へのマッピング。
InventoryItem sync (sync.py) の後継。

差分管理は bmc-synced タグで行う (手動作成 Module には触れない)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .normalizer import NormalizedComponent

logger = logging.getLogger("netbox_bmc.module_sync")

SYNC_TAG_SLUG = "bmc-synced"

KIND_TO_PROFILE = {
    "cpu": "CPU",
    "memory": "Memory",
    "drive": "Hard disk",
    "psu": "Power supply",
    "fan": "Fan",
    "pci": "Expansion card",
}


@dataclass
class DiffEntry:
    status: str  # new | updated | unchanged | removed
    normalized_name: str
    nc: NormalizedComponent | None   # None when status == "removed"
    existing_module: object | None   # Module instance; None when status == "new"
    bay_exists: bool
    old_serial: str = ""
    old_part_id: str = ""


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    messages: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"created={self.created} updated={self.updated} "
                f"deleted={self.deleted} unchanged={self.unchanged}")


def compute_diff(device, normalized_components: list[NormalizedComponent]) -> list[DiffEntry]:
    from dcim.models import Module, ModuleBay

    existing: dict[str, object] = {}
    for module in Module.objects.filter(
        module_bay__device=device,
        tags__slug=SYNC_TAG_SLUG,
    ).select_related("module_bay", "module_type"):
        existing[module.module_bay.name] = module

    bay_names = set(
        ModuleBay.objects.filter(device=device).values_list("name", flat=True)
    )

    desired = {nc.normalized_name: nc for nc in normalized_components}
    result: list[DiffEntry] = []

    for name, nc in desired.items():
        bay_exists = name in bay_names
        if name not in existing:
            result.append(DiffEntry(
                status="new", normalized_name=name, nc=nc,
                existing_module=None, bay_exists=bay_exists,
            ))
        else:
            module = existing[name]
            changed = (
                module.serial != nc.component.serial
                or module.module_type.part_number != nc.component.part_id
            )
            result.append(DiffEntry(
                status="updated" if changed else "unchanged",
                normalized_name=name, nc=nc,
                existing_module=module, bay_exists=bay_exists,
                old_serial=module.serial,
                old_part_id=module.module_type.part_number,
            ))

    for name, module in existing.items():
        if name not in desired:
            result.append(DiffEntry(
                status="removed", normalized_name=name, nc=None,
                existing_module=module, bay_exists=True,
            ))

    return result


def _get_sync_tag():
    from extras.models import Tag
    tag, _ = Tag.objects.get_or_create(
        slug=SYNC_TAG_SLUG,
        defaults={
            "name": "BMC Synced",
            "color": "2196f3",
            "description": "Managed by netbox-bmc module sync",
        },
    )
    return tag


def _get_profile(kind: str):
    from dcim.models.modules import ModuleTypeProfile
    profile_name = KIND_TO_PROFILE.get(kind)
    if not profile_name:
        return None
    return ModuleTypeProfile.objects.filter(name=profile_name).first()


def _get_manufacturer(name: str):
    from django.utils.text import slugify
    from dcim.models import Manufacturer
    name = name.strip() or "Unknown"
    slug = slugify(name)[:100]
    obj, _ = Manufacturer.objects.get_or_create(slug=slug, defaults={"name": name})
    return obj


_MEMORY_CLASS_MAP = {"DDR3": "DDR3", "DDR4": "DDR4", "DDR5": "DDR5"}


def _set_module_type_attributes(module_type, entry: dict) -> None:
    """Set attribute_data on ModuleType for profile-specific fields."""
    kind = entry.get("kind", "")
    extra = entry.get("extra", {})
    attrs = {}

    if kind == "cpu":
        cores = extra.get("cores", 0)
        if cores:
            attrs["cores"] = cores
        speed_mhz = extra.get("speed_mhz", 0)
        if speed_mhz:
            attrs["speed"] = round(speed_mhz / 1000, 2)
        arch = extra.get("architecture", "")
        if arch:
            attrs["architecture"] = arch

    elif kind == "drive":
        desc = entry.get("description", "").upper()
        if "NVME" in desc:
            attrs["type"] = "NVME"
        elif "SSD" in desc:
            attrs["type"] = "SSD"
        else:
            attrs["type"] = "HD"

    elif kind == "memory":
        cap_mib = extra.get("capacity_mib", 0)
        if cap_mib:
            attrs["size"] = cap_mib // 1024
        mem_class = _MEMORY_CLASS_MAP.get(extra.get("memory_device_type", ""))
        if mem_class:
            attrs["class"] = mem_class
        speed = extra.get("operating_speed_mhz", 0)
        if speed:
            attrs["data_rate"] = speed
        if "ecc" in extra:
            attrs["ecc"] = extra["ecc"]

    if not attrs or module_type.attribute_data == attrs:
        return
    module_type.attribute_data = attrs
    module_type.save(update_fields=["attribute_data"])


def _set_module_custom_fields(module, entry: dict) -> None:
    path = entry.get("source_path", "")
    firmware = entry.get("firmware", "")
    changed = False
    if path and module.custom_field_data.get("bmc_redfish_path") != path:
        module.custom_field_data["bmc_redfish_path"] = path
        changed = True
    if firmware and module.custom_field_data.get("bmc_firmware_version") != firmware:
        module.custom_field_data["bmc_firmware_version"] = firmware
        changed = True
    if changed:
        module.save(update_fields=["custom_field_data"])


def apply_firmware_to_device(device, firmware: dict[str, str]) -> None:
    """Write firmware inventory dict to Device's bmc_firmware_inventory custom field."""
    if device.custom_field_data.get("bmc_firmware_inventory") == firmware:
        return
    device.custom_field_data["bmc_firmware_inventory"] = firmware
    device.save(update_fields=["custom_field_data"])


def entry_to_dict(entry: DiffEntry) -> dict:
    nc = entry.nc
    return {
        "status": entry.status,
        "normalized_name": entry.normalized_name,
        "kind": nc.component.kind if nc else "",
        "raw_name": nc.component.name if nc else "",
        "serial": nc.component.serial if nc else "",
        "part_id": nc.component.part_id if nc else "",
        "manufacturer": nc.component.manufacturer if nc else "",
        "source_path": nc.component.source_path if nc else "",
        "firmware": nc.component.firmware if nc else "",
        "description": nc.component.description if nc else "",
        "extra": nc.component.extra if nc else {},
        "bay_exists": entry.bay_exists,
        "old_serial": entry.old_serial,
        "old_part_id": entry.old_part_id,
    }


def apply_module_sync(
    device,
    session_entries: list[dict],
    selected_names: set[str],
    delete_names: set[str],
) -> SyncReport:
    from dcim.models import Module, ModuleBay, ModuleType

    report = SyncReport()
    tag = _get_sync_tag()

    for entry in session_entries:
        name = entry["normalized_name"]
        status = entry["status"]

        if status == "removed":
            if name in delete_names:
                try:
                    bay = ModuleBay.objects.get(device=device, name=name)
                    deleted, _ = Module.objects.filter(
                        module_bay=bay, tags__slug=SYNC_TAG_SLUG
                    ).delete()
                    report.deleted += deleted
                except ModuleBay.DoesNotExist:
                    pass
            continue

        if name not in selected_names:
            report.unchanged += 1
            continue

        bay, _ = ModuleBay.objects.get_or_create(
            device=device, name=name,
            defaults={"label": name},
        )

        manufacturer = _get_manufacturer(entry.get("manufacturer", ""))
        part_id = (entry.get("part_id") or entry.get("kind", "unknown"))[:100]
        profile = _get_profile(entry.get("kind", ""))
        module_type, created = ModuleType.objects.get_or_create(
            manufacturer=manufacturer,
            model=part_id,
            defaults={"part_number": part_id, "profile": profile},
        )
        if not created and profile and module_type.profile_id != profile.pk:
            module_type.profile = profile
            module_type.save(update_fields=["profile"])
        _set_module_type_attributes(module_type, entry)

        existing_qs = Module.objects.filter(module_bay=bay, tags__slug=SYNC_TAG_SLUG)

        if status == "new":
            module = Module(
                device=device,
                module_bay=bay,
                module_type=module_type,
                serial=(entry.get("serial") or "")[:50],
                description=(entry.get("description") or "")[:200],
            )
            try:
                module.save()
            except Exception as e:
                # ponytail: catches ValidationError from disabled ModuleBay (NetBox 4.6+)
                report.messages.append(f"Skipped {name}: {e}")
                continue
            module.tags.add(tag)
            _set_module_custom_fields(module, entry)
            report.created += 1
        else:
            module = existing_qs.first()
            if module:
                module.serial = (entry.get("serial") or "")[:50]
                module.module_type = module_type
                module.description = (entry.get("description") or "")[:200]
                try:
                    module.save()
                except Exception as e:
                    report.messages.append(f"Skipped {name}: {e}")
                    continue
                _set_module_custom_fields(module, entry)
                report.updated += 1

    logger.info("Module sync for %s: %s", device, report.summary())
    return report
