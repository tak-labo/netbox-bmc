from netbox_bmc.inventory import Component
from netbox_bmc.normalizer import normalize


def _cpu(name, serial="", part_id=""):
    return Component(kind="cpu", name=name, serial=serial, part_id=part_id)


def test_single_cpu_is_cpu_0():
    result = normalize([_cpu("CPU.Socket.1")])
    assert len(result) == 1
    assert result[0].normalized_name == "CPU 0"
    assert result[0].component.name == "CPU.Socket.1"


def test_two_cpus_sorted_by_raw_name():
    comps = [_cpu("CPU.Socket.2"), _cpu("CPU.Socket.1")]
    result = normalize(comps)
    assert [r.normalized_name for r in result] == ["CPU 0", "CPU 1"]
    assert result[0].component.name == "CPU.Socket.1"


def test_processor_variant_becomes_cpu():
    result = normalize([Component(kind="cpu", name="Processor 0")])
    assert result[0].normalized_name == "CPU 0"


def test_nic_excluded_from_modules():
    result = normalize([Component(kind="nic", name="eth0")])
    assert result == []


def test_memory_letter_slot_natural_sort():
    comps = [
        Component(kind="memory", name="DIMM.A2"),
        Component(kind="memory", name="DIMM.A1"),
        Component(kind="memory", name="DIMM.B1"),
    ]
    result = normalize(comps)
    assert [r.normalized_name for r in result] == ["Memory 0", "Memory 1", "Memory 2"]
    assert result[0].component.name == "DIMM.A1"


def test_pci_kind_uses_pci_label():
    result = normalize([Component(kind="pci", name="PCIe.Slot.1")])
    assert result[0].normalized_name == "PCI 0"


def test_mixed_kinds_all_start_at_0():
    comps = [
        Component(kind="cpu", name="CPU0"),
        Component(kind="memory", name="DIMM0"),
        Component(kind="pci", name="PCIe0"),
    ]
    result = normalize(comps)
    assert {r.normalized_name for r in result} == {"CPU 0", "Memory 0", "PCI 0"}


def test_firmware_kind_uses_firmware_label():
    result = normalize([Component(kind="firmware", name="BIOS")])
    assert result[0].normalized_name == "Firmware 0"


def test_duplicate_raw_names_passthrough():
    # Deduplication of raw names is the driver's responsibility.
    # If the driver returns the same component twice, both get normalized names.
    comps = [_cpu("CPU.Socket.1"), _cpu("CPU.Socket.1")]
    result = normalize(comps)
    assert len(result) == 2
    assert result[0].normalized_name == "CPU 0"
    assert result[1].normalized_name == "CPU 1"
