"""
Tests for Redfish driver PSU and Fan collection.

Tests run against mocked Redfish HTTP responses without a real BMC.
"""
from unittest.mock import patch, MagicMock
from netbox_bmc.drivers.redfish import RedfishDriver


def make_driver():
    """Create a RedfishDriver with _login mocked to avoid HTTP calls."""
    with patch.object(RedfishDriver, "_login"):
        return RedfishDriver("bmc.example.com", "admin", "pass")


# --- PSU -------------------------------------------------------------------

def test_collect_psu_returns_component():
    """PSU collection should return a Component with expected fields."""
    driver = make_driver()
    sysres = {"Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}
    chassis = {"Power": {"@odata.id": "/redfish/v1/Chassis/1/Power"}}
    power = {
        "PowerSupplies": [{
            "MemberId": "0",
            "Name": "Power Supply 0",
            "Manufacturer": "Delta",
            "PartNumber": "DPS-800AB",
            "SerialNumber": "PSU_SN_001",
            "FirmwareVersion": "1.2",
            "Status": {"State": "Enabled"},
        }]
    }
    with patch.object(driver, "_get_optional", side_effect=[chassis, power]):
        comps = driver._collect_psu(sysres)
    assert len(comps) == 1
    assert comps[0].kind == "psu"
    assert comps[0].serial == "PSU_SN_001"
    assert comps[0].part_id == "DPS-800AB"
    assert comps[0].firmware == "1.2"


def test_collect_psu_absent_skipped():
    """PSU with Absent state should be skipped."""
    driver = make_driver()
    sysres = {"Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}
    chassis = {"Power": {"@odata.id": "/redfish/v1/Chassis/1/Power"}}
    power = {
        "PowerSupplies": [{"MemberId": "0", "Status": {"State": "Absent"}}]
    }
    with patch.object(driver, "_get_optional", side_effect=[chassis, power]):
        comps = driver._collect_psu(sysres)
    assert comps == []


def test_collect_psu_no_chassis_link():
    """PSU collection should return empty list when no Chassis links."""
    driver = make_driver()
    comps = driver._collect_psu({"Links": {}})
    assert comps == []


# --- Fan -------------------------------------------------------------------

def test_collect_fans_returns_component():
    """Fan collection should return a Component with expected fields."""
    driver = make_driver()
    sysres = {"Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}
    chassis = {"Thermal": {"@odata.id": "/redfish/v1/Chassis/1/Thermal"}}
    thermal = {
        "Fans": [{
            "MemberId": "0",
            "FanName": "Fan 0",
            "Manufacturer": "Delta",
            "Status": {"State": "Enabled"},
        }]
    }
    with patch.object(driver, "_get_optional", side_effect=[chassis, thermal]):
        comps = driver._collect_fans(sysres)
    assert len(comps) == 1
    assert comps[0].kind == "fan"
    assert comps[0].description == "Fan 0"


def test_collect_fans_absent_skipped():
    """Fan with Absent state should be skipped."""
    driver = make_driver()
    sysres = {"Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}
    chassis = {"Thermal": {"@odata.id": "/redfish/v1/Chassis/1/Thermal"}}
    thermal = {"Fans": [{"MemberId": "0", "Status": {"State": "Absent"}}]}
    with patch.object(driver, "_get_optional", side_effect=[chassis, thermal]):
        comps = driver._collect_fans(sysres)
    assert comps == []


# --- PCIe ------------------------------------------------------------------

def test_collect_pcie_devices_returns_component():
    driver = make_driver()
    sysres = {"PCIeDevices": {"@odata.id": "/redfish/v1/Systems/1/PCIeDevices"}}
    pcie_member = {
        "@odata.id": "/redfish/v1/Systems/1/PCIeDevices/NIC.Slot.1",
        "Id": "NIC.Slot.1",
        "Name": "Intel X710",
        "Manufacturer": "Intel",
        "Model": "X710-DA2",
        "SerialNumber": "PCIESN001",
        "Status": {"State": "Enabled"},
    }
    with patch.object(driver, "_get_optional", side_effect=[
        {"Members": [{"@odata.id": "/redfish/v1/Systems/1/PCIeDevices/NIC.Slot.1"}]},
        pcie_member,
    ]):
        comps = driver._collect_pcie_devices(sysres)
    assert len(comps) == 1
    assert comps[0].kind == "pci"
    assert comps[0].name == "NIC.Slot.1"
    assert comps[0].manufacturer == "Intel"
    assert comps[0].part_id == "X710-DA2"
    assert comps[0].serial == "PCIESN001"


def test_collect_pcie_absent_skipped():
    driver = make_driver()
    sysres = {"PCIeDevices": {"@odata.id": "/redfish/v1/Systems/1/PCIeDevices"}}
    with patch.object(driver, "_get_optional", side_effect=[
        {"Members": [{"@odata.id": "/redfish/v1/Systems/1/PCIeDevices/Slot.2"}]},
        {"Id": "Slot.2", "Status": {"State": "Absent"}},
    ]):
        comps = driver._collect_pcie_devices(sysres)
    assert comps == []


def test_collect_pcie_no_collection_key():
    driver = make_driver()
    comps = driver._collect_pcie_devices({})
    assert comps == []
