"""Tests for System Event Log (get_event_log())."""
from unittest.mock import MagicMock, patch

from netbox_bmc.drivers.ipmi import IPMIDriver
from netbox_bmc.drivers.redfish import RedfishDriver


# --- Redfish -----------------------------------------------------------

def make_redfish_driver():
    with patch.object(RedfishDriver, "_login"):
        return RedfishDriver("bmc.example.com", "admin", "pass")


def test_redfish_event_log_inlined_members():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    mgr = {"LogServices": {"@odata.id": "/redfish/v1/Managers/1/LogServices"}}
    log_service = {"Entries": {"@odata.id": "/redfish/v1/Managers/1/LogServices/Log/Entries"}}
    entries_coll = {
        "Members": [
            {"Created": "2024-01-01T00:00:00Z", "Severity": "OK", "Message": "Boot complete"},
            {"Created": "2024-01-02T00:00:00Z", "Severity": "Critical", "Message": "PSU failure",
             "SensorType": "Power Supply"},
        ]
    }

    def fake_get_optional(ref):
        return {
            "/redfish/v1/Managers/1/LogServices/Log/Entries": entries_coll,
        }[ref]

    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", side_effect=[[mgr], [log_service]]), \
         patch.object(driver, "_get_optional", side_effect=fake_get_optional):
        entries = driver.get_event_log(limit=20)

    assert len(entries) == 2
    # newest first
    assert entries[0].message == "PSU failure"
    assert entries[0].severity == "Critical"
    assert entries[0].sensor_type == "Power Supply"
    assert entries[1].message == "Boot complete"


def test_redfish_event_log_respects_limit():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    mgr = {"LogServices": {"@odata.id": "/redfish/v1/Managers/1/LogServices"}}
    log_service = {"Entries": {"@odata.id": "/redfish/v1/Managers/1/LogServices/Log/Entries"}}
    entries_coll = {
        "Members": [
            {"Created": f"2024-01-{i:02d}T00:00:00Z", "Message": f"event {i}"}
            for i in range(1, 11)
        ]
    }

    def fake_get_optional(ref):
        return {"/redfish/v1/Managers/1/LogServices/Log/Entries": entries_coll}[ref]

    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", side_effect=[[mgr], [log_service]]), \
         patch.object(driver, "_get_optional", side_effect=fake_get_optional):
        entries = driver.get_event_log(limit=3)

    assert len(entries) == 3
    assert entries[0].message == "event 10"


def test_redfish_event_log_no_log_services():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    mgr = {}
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", side_effect=[[mgr], []]):
        entries = driver.get_event_log()

    assert entries == []


# --- IPMI ----------------------------------------------------------------

def make_ipmi_driver():
    with patch("pyghmi.ipmi.command.Command", return_value=MagicMock()):
        return IPMIDriver("192.168.0.1", "admin", "admin")


def test_ipmi_event_log_recent_first():
    driver = make_ipmi_driver()
    driver.cmd.get_event_log.return_value = iter([
        {"timestamp": "2024-01-01 00:00:00", "event": "Boot complete",
         "component": "System", "severity": 0},
        {"timestamp": "2024-01-02 00:00:00", "event": "PSU failure",
         "component": "PSU1", "severity": 2},
    ])

    entries = driver.get_event_log(limit=20)

    assert len(entries) == 2
    assert entries[0].message == "PSU failure"
    assert entries[0].severity == "Critical"
    assert entries[1].message == "Boot complete"
    assert entries[1].severity == "OK"


def test_ipmi_event_log_respects_limit():
    driver = make_ipmi_driver()
    driver.cmd.get_event_log.return_value = iter([
        {"timestamp": str(i), "event": f"event {i}", "component": "", "severity": 0}
        for i in range(10)
    ])

    entries = driver.get_event_log(limit=3)

    assert len(entries) == 3
    assert entries[0].message == "event 9"


def test_ipmi_event_log_wraps_errors():
    from netbox_bmc.drivers.base import BMCError
    import pytest

    driver = make_ipmi_driver()
    driver.cmd.get_event_log.side_effect = Exception("SDR error")

    with pytest.raises(BMCError):
        driver.get_event_log()
