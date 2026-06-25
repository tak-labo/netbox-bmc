"""Tests for IPMI driver SystemInfo field mapping."""
from unittest.mock import MagicMock, patch

from netbox_bmc.drivers.ipmi import IPMIDriver


def make_driver():
    with patch("pyghmi.ipmi.command.Command", return_value=MagicMock()):
        return IPMIDriver("192.168.0.1", "admin", "admin")


def run_inventory(driver, fru_entries):
    driver.cmd.get_inventory.return_value = iter(fru_entries)
    return driver.get_inventory()


def test_system_info_from_standard_fields():
    """Standard Manufacturer/Product name/Serial Number fields are used."""
    driver = make_driver()
    result = run_inventory(driver, [
        ("System", {
            "Manufacturer": "Dell",
            "Product name": "PowerEdge R740",
            "Serial Number": "SN123",
            "UUID": "abc-def",
        })
    ])
    assert result.system.manufacturer == "Dell"
    assert result.system.model == "PowerEdge R740"
    assert result.system.serial == "SN123"


def test_system_info_falls_back_to_board_fields():
    """Board manufacturer/product name/serial number used when standard fields are None."""
    driver = make_driver()
    result = run_inventory(driver, [
        ("System", {
            "Manufacturer": None,
            "Product name": None,
            "Serial Number": None,
            "Board manufacturer": "ASRockRack",
            "Board product name": "E3C242D4U2-2T",
            "Board serial number": "181477100000471",
            "UUID": None,
        })
    ])
    assert result.system.manufacturer == "ASRockRack"
    assert result.system.model == "E3C242D4U2-2T"
    assert result.system.serial == "181477100000471"


def test_system_info_standard_takes_priority_over_board():
    """Standard fields take priority over Board fields when both are present."""
    driver = make_driver()
    result = run_inventory(driver, [
        ("System", {
            "Manufacturer": "Dell",
            "Product name": "PowerEdge",
            "Serial Number": "SN999",
            "Board manufacturer": "ASRockRack",
            "Board product name": "X570D4U",
            "Board serial number": "T80-xxx",
        })
    ])
    assert result.system.manufacturer == "Dell"
    assert result.system.model == "PowerEdge"
    assert result.system.serial == "SN999"
