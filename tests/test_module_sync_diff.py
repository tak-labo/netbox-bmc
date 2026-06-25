from unittest.mock import MagicMock, patch

from netbox_bmc.inventory import Component
from netbox_bmc.module_sync import compute_diff
from netbox_bmc.normalizer import NormalizedComponent


def _nc(name, serial="S1", part_id="P1", kind="cpu"):
    comp = Component(kind=kind, name=name, serial=serial, part_id=part_id)
    return NormalizedComponent(normalized_name=name, component=comp)


def _mock_module(bay_name, serial, part_number):
    m = MagicMock()
    m.module_bay.name = bay_name
    m.serial = serial
    m.module_type.part_number = part_number
    return m


@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_new_component(mock_module, mock_bay):
    mock_module.objects.filter.return_value.select_related.return_value = []
    mock_bay.objects.filter.return_value.values_list.return_value = []

    entries = compute_diff(MagicMock(), [_nc("CPU 0")])

    assert len(entries) == 1
    assert entries[0].status == "new"
    assert entries[0].normalized_name == "CPU 0"
    assert not entries[0].bay_exists


@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_new_component_bay_already_exists(mock_module, mock_bay):
    mock_module.objects.filter.return_value.select_related.return_value = []
    mock_bay.objects.filter.return_value.values_list.return_value = ["CPU 0"]

    entries = compute_diff(MagicMock(), [_nc("CPU 0")])

    assert entries[0].status == "new"
    assert entries[0].bay_exists


@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_unchanged_when_serial_and_part_match(mock_module, mock_bay):
    existing = _mock_module("CPU 0", serial="S1", part_number="P1")
    mock_module.objects.filter.return_value.select_related.return_value = [existing]
    mock_bay.objects.filter.return_value.values_list.return_value = ["CPU 0"]

    entries = compute_diff(MagicMock(), [_nc("CPU 0", serial="S1", part_id="P1")])

    assert entries[0].status == "unchanged"


@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_updated_when_serial_changes(mock_module, mock_bay):
    existing = _mock_module("CPU 0", serial="OLD", part_number="P1")
    mock_module.objects.filter.return_value.select_related.return_value = [existing]
    mock_bay.objects.filter.return_value.values_list.return_value = ["CPU 0"]

    entries = compute_diff(MagicMock(), [_nc("CPU 0", serial="NEW", part_id="P1")])

    assert entries[0].status == "updated"
    assert entries[0].old_serial == "OLD"
    assert entries[0].old_part_id == "P1"


@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_updated_when_part_changes(mock_module, mock_bay):
    existing = _mock_module("Memory 0", serial="S1", part_number="OLD_PART")
    mock_module.objects.filter.return_value.select_related.return_value = [existing]
    mock_bay.objects.filter.return_value.values_list.return_value = ["Memory 0"]

    entries = compute_diff(MagicMock(), [_nc("Memory 0", serial="S1", part_id="NEW_PART")])

    assert entries[0].status == "updated"
    assert entries[0].old_part_id == "OLD_PART"


@patch("dcim.models.ModuleBay")
@patch("dcim.models.Module")
def test_removed_when_not_in_desired(mock_module, mock_bay):
    existing = _mock_module("CPU 0", serial="S1", part_number="P1")
    mock_module.objects.filter.return_value.select_related.return_value = [existing]
    mock_bay.objects.filter.return_value.values_list.return_value = ["CPU 0"]

    entries = compute_diff(MagicMock(), [])  # nothing desired

    assert entries[0].status == "removed"
    assert entries[0].normalized_name == "CPU 0"
    assert entries[0].nc is None
