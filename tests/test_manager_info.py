"""Tests for BMC-self firmware/health info (get_manager_info())."""
from unittest.mock import MagicMock, patch

from netbox_bmc.drivers.ipmi import IPMIDriver
from netbox_bmc.drivers.redfish import RedfishDriver

# --- Redfish -----------------------------------------------------------

def make_redfish_driver():
    with patch.object(RedfishDriver, "_login"):
        return RedfishDriver("bmc.example.com", "admin", "pass")


def test_redfish_manager_info():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    mgr = {
        "FirmwareVersion": "2.75.75.75",
        "Status": {"Health": "OK"},
        "Model": "iDRAC",
        "Name": "Manager",
    }
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", return_value=[mgr]):
        info = driver.get_manager_info()

    assert info.firmware_version == "2.75.75.75"
    assert info.health == "OK"
    assert info.model == "iDRAC"
    assert info.name == "Manager"


# --- IPMI ----------------------------------------------------------------

def make_ipmi_driver():
    with patch("pyghmi.ipmi.command.Command", return_value=MagicMock()):
        return IPMIDriver("192.168.0.1", "admin", "admin")


def test_ipmi_manager_info_healthy():
    driver = make_ipmi_driver()
    # Get Device ID raw response: data[2]=firmware major (0x02), data[3]=minor BCD (0x15 -> "1" "5")
    driver.cmd.raw_command.return_value = {"data": [0, 0, 0x02, 0x15]}
    driver.cmd.get_health.return_value = {"health": 0, "badreadings": []}

    info = driver.get_manager_info()

    assert info.firmware_version == "2.15"
    assert info.health == "OK"


def test_ipmi_manager_info_critical_health():
    driver = make_ipmi_driver()
    driver.cmd.raw_command.return_value = {"data": [0, 0, 0x01, 0x00]}
    driver.cmd.get_health.return_value = {"health": 2, "badreadings": ["PSU1 fault"]}

    info = driver.get_manager_info()

    assert info.health == "Critical"


def test_ipmi_manager_info_health_failure_is_best_effort():
    """get_health() may fail on some BMCs; health stays empty but firmware still returned."""
    driver = make_ipmi_driver()
    driver.cmd.raw_command.return_value = {"data": [0, 0, 0x01, 0x00]}
    driver.cmd.get_health.side_effect = Exception("boom")

    info = driver.get_manager_info()

    assert info.firmware_version == "1.00"
    assert info.health == ""
