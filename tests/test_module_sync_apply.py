from unittest.mock import MagicMock, patch, call

from netbox_bmc.inventory import Component
from netbox_bmc.module_sync import (
    DiffEntry,
    SyncReport,
    _set_module_custom_fields,
    apply_module_sync,
    entry_to_dict,
)
from netbox_bmc.normalizer import NormalizedComponent


# ---------------------------------------------------------------------------
# entry_to_dict
# ---------------------------------------------------------------------------

def _make_nc(kind="cpu", name="CPU.Socket.1", serial="SN1", part_id="P1",
             manufacturer="Intel", source_path="/redfish/v1/foo", firmware="2.0",
             description="32C"):
    comp = Component(
        kind=kind, name=name, serial=serial, part_id=part_id,
        manufacturer=manufacturer, source_path=source_path,
        firmware=firmware, description=description,
    )
    return NormalizedComponent(normalized_name=f"{kind.upper()} 0", component=comp)


def test_entry_to_dict_new_entry():
    nc = _make_nc()
    entry = DiffEntry(status="new", normalized_name="CPU 0", nc=nc,
                      existing_module=None, bay_exists=False)
    d = entry_to_dict(entry)
    assert d["status"] == "new"
    assert d["normalized_name"] == "CPU 0"
    assert d["kind"] == "cpu"
    assert d["raw_name"] == "CPU.Socket.1"
    assert d["serial"] == "SN1"
    assert d["part_id"] == "P1"
    assert d["manufacturer"] == "Intel"
    assert d["source_path"] == "/redfish/v1/foo"
    assert d["firmware"] == "2.0"
    assert d["description"] == "32C"
    assert d["bay_exists"] is False
    assert d["old_serial"] == ""
    assert d["old_part_id"] == ""


def test_entry_to_dict_removed_entry_nc_is_none():
    entry = DiffEntry(status="removed", normalized_name="CPU 0", nc=None,
                      existing_module=MagicMock(), bay_exists=True,
                      old_serial="OLD_SN", old_part_id="OLD_PART")
    d = entry_to_dict(entry)
    assert d["status"] == "removed"
    assert d["kind"] == ""
    assert d["serial"] == ""
    assert d["manufacturer"] == ""
    assert d["old_serial"] == "OLD_SN"
    assert d["old_part_id"] == "OLD_PART"
    assert d["bay_exists"] is True


# ---------------------------------------------------------------------------
# _set_module_custom_fields
# ---------------------------------------------------------------------------

def test_set_custom_fields_sets_both_values():
    module = MagicMock()
    module.custom_field_data = {}
    _set_module_custom_fields(module, {"source_path": "/redfish/v1/foo", "firmware": "1.0"})
    assert module.custom_field_data["bmc_redfish_path"] == "/redfish/v1/foo"
    assert module.custom_field_data["bmc_firmware_version"] == "1.0"
    module.save.assert_called_once_with(update_fields=["custom_field_data"])


def test_set_custom_fields_no_save_when_unchanged():
    module = MagicMock()
    module.custom_field_data = {
        "bmc_redfish_path": "/redfish/v1/foo",
        "bmc_firmware_version": "1.0",
    }
    _set_module_custom_fields(module, {"source_path": "/redfish/v1/foo", "firmware": "1.0"})
    module.save.assert_not_called()


def test_set_custom_fields_skips_empty_values():
    module = MagicMock()
    module.custom_field_data = {}
    _set_module_custom_fields(module, {"source_path": "", "firmware": ""})
    module.save.assert_not_called()
    assert "bmc_redfish_path" not in module.custom_field_data


def test_set_custom_fields_partial_update():
    module = MagicMock()
    module.custom_field_data = {"bmc_redfish_path": "/old"}
    _set_module_custom_fields(module, {"source_path": "/new", "firmware": ""})
    assert module.custom_field_data["bmc_redfish_path"] == "/new"
    assert "bmc_firmware_version" not in module.custom_field_data
    module.save.assert_called_once_with(update_fields=["custom_field_data"])


# ---------------------------------------------------------------------------
# apply_module_sync helpers
# ---------------------------------------------------------------------------

def _make_entry(status="new", name="CPU 0", serial="SN1", part_id="Xeon",
                manufacturer="Intel", kind="cpu", source_path="", firmware="",
                description="32C"):
    return {
        "status": status,
        "normalized_name": name,
        "serial": serial,
        "part_id": part_id,
        "manufacturer": manufacturer,
        "kind": kind,
        "source_path": source_path,
        "firmware": firmware,
        "description": description,
    }


def _setup_apply_mocks(mock_module_cls, mock_bay_cls, mock_type_cls,
                       mock_get_mfr, mock_get_tag):
    tag = MagicMock()
    mock_get_tag.return_value = tag

    bay = MagicMock()
    mock_bay_cls.objects.get_or_create.return_value = (bay, True)
    mock_bay_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})

    mfr = MagicMock()
    mock_get_mfr.return_value = mfr

    module_type = MagicMock()
    mock_type_cls.objects.get_or_create.return_value = (module_type, True)

    module = MagicMock()
    module.custom_field_data = {}
    mock_module_cls.return_value = module

    return tag, bay, mfr, module_type, module


# ---------------------------------------------------------------------------
# apply_module_sync
# ---------------------------------------------------------------------------

@patch("netbox_bmc.module_sync._get_sync_tag")
@patch("netbox_bmc.module_sync._get_manufacturer")
@patch("dcim.models.ModuleType")
@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_apply_creates_new_module(mock_module_cls, mock_bay_cls, mock_type_cls,
                                  mock_get_mfr, mock_get_tag):
    device = MagicMock()
    tag, bay, mfr, module_type, module = _setup_apply_mocks(
        mock_module_cls, mock_bay_cls, mock_type_cls, mock_get_mfr, mock_get_tag
    )

    entry = _make_entry(status="new", name="CPU 0", serial="SN001")
    report = apply_module_sync(device, [entry], {"CPU 0"}, set())

    assert report.created == 1
    assert report.updated == 0
    assert report.deleted == 0
    module.save.assert_called()
    module.tags.add.assert_called_with(tag)


@patch("netbox_bmc.module_sync._get_sync_tag")
@patch("netbox_bmc.module_sync._get_manufacturer")
@patch("dcim.models.ModuleType")
@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_apply_updates_existing_module(mock_module_cls, mock_bay_cls, mock_type_cls,
                                       mock_get_mfr, mock_get_tag):
    device = MagicMock()
    tag, bay, mfr, module_type, module = _setup_apply_mocks(
        mock_module_cls, mock_bay_cls, mock_type_cls, mock_get_mfr, mock_get_tag
    )
    existing_module = MagicMock()
    existing_module.custom_field_data = {}
    mock_module_cls.objects.filter.return_value.first.return_value = existing_module

    entry = _make_entry(status="updated", name="CPU 0", serial="NEW_SN")
    report = apply_module_sync(device, [entry], {"CPU 0"}, set())

    assert report.updated == 1
    assert report.created == 0
    existing_module.save.assert_called()


@patch("netbox_bmc.module_sync._get_sync_tag")
@patch("netbox_bmc.module_sync._get_manufacturer")
@patch("dcim.models.ModuleType")
@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_apply_skips_unselected_entry(mock_module_cls, mock_bay_cls, mock_type_cls,
                                      mock_get_mfr, mock_get_tag):
    device = MagicMock()
    _setup_apply_mocks(mock_module_cls, mock_bay_cls, mock_type_cls, mock_get_mfr, mock_get_tag)

    entry = _make_entry(status="unchanged", name="Memory 0")
    report = apply_module_sync(device, [entry], set(), set())  # nothing selected

    assert report.unchanged == 1
    assert report.created == 0
    mock_bay_cls.objects.get_or_create.assert_not_called()


@patch("netbox_bmc.module_sync._get_sync_tag")
@patch("netbox_bmc.module_sync._get_manufacturer")
@patch("dcim.models.ModuleType")
@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_apply_deletes_removed_module(mock_module_cls, mock_bay_cls, mock_type_cls,
                                      mock_get_mfr, mock_get_tag):
    device = MagicMock()
    tag, bay, *_ = _setup_apply_mocks(
        mock_module_cls, mock_bay_cls, mock_type_cls, mock_get_mfr, mock_get_tag
    )
    mock_bay_cls.objects.get.return_value = bay
    mock_module_cls.objects.filter.return_value.delete.return_value = (2, {})

    entry = _make_entry(status="removed", name="Drive 0")
    report = apply_module_sync(device, [entry], set(), {"Drive 0"})

    assert report.deleted == 2
    mock_module_cls.objects.filter.return_value.delete.assert_called_once()


@patch("netbox_bmc.module_sync._get_sync_tag")
@patch("netbox_bmc.module_sync._get_manufacturer")
@patch("dcim.models.ModuleType")
@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_apply_skips_removed_not_in_delete_names(mock_module_cls, mock_bay_cls, mock_type_cls,
                                                  mock_get_mfr, mock_get_tag):
    device = MagicMock()
    _setup_apply_mocks(mock_module_cls, mock_bay_cls, mock_type_cls, mock_get_mfr, mock_get_tag)

    entry = _make_entry(status="removed", name="Drive 0")
    report = apply_module_sync(device, [entry], set(), set())  # delete_names empty

    assert report.deleted == 0
    mock_module_cls.objects.filter.return_value.delete.assert_not_called()


@patch("netbox_bmc.module_sync._get_sync_tag")
@patch("netbox_bmc.module_sync._get_manufacturer")
@patch("dcim.models.ModuleType")
@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_apply_serial_truncated_to_50_chars(mock_module_cls, mock_bay_cls, mock_type_cls,
                                             mock_get_mfr, mock_get_tag):
    device = MagicMock()
    tag, bay, mfr, module_type, module = _setup_apply_mocks(
        mock_module_cls, mock_bay_cls, mock_type_cls, mock_get_mfr, mock_get_tag
    )

    long_serial = "X" * 100
    entry = _make_entry(status="new", name="CPU 0", serial=long_serial)
    apply_module_sync(device, [entry], {"CPU 0"}, set())

    # Module was instantiated — check serial was truncated
    call_kwargs = mock_module_cls.call_args
    assert len(call_kwargs.kwargs["serial"]) == 50


@patch("netbox_bmc.module_sync._get_sync_tag")
@patch("netbox_bmc.module_sync._get_manufacturer")
@patch("dcim.models.ModuleType")
@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_apply_report_summary(mock_module_cls, mock_bay_cls, mock_type_cls,
                               mock_get_mfr, mock_get_tag):
    device = MagicMock()
    tag, bay, mfr, module_type, module = _setup_apply_mocks(
        mock_module_cls, mock_bay_cls, mock_type_cls, mock_get_mfr, mock_get_tag
    )

    entries = [
        _make_entry(status="new", name="CPU 0"),
        _make_entry(status="unchanged", name="Memory 0"),
    ]
    report = apply_module_sync(device, entries, {"CPU 0"}, set())

    assert "created=1" in report.summary()
    assert "unchanged=1" in report.summary()
