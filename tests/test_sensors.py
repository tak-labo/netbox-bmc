"""Tests for sensor telemetry (get_sensors())."""
from unittest.mock import MagicMock, patch

from netbox_bmc.drivers.ipmi import IPMIDriver
from netbox_bmc.drivers.redfish import RedfishDriver

# --- Redfish -----------------------------------------------------------

def make_redfish_driver():
    with patch.object(RedfishDriver, "_login"):
        return RedfishDriver("bmc.example.com", "admin", "pass")


def test_redfish_get_sensors_reads_thermal_and_power():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    sysres = {"Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}
    chassis = {
        "Thermal": {"@odata.id": "/redfish/v1/Chassis/1/Thermal"},
        "Power": {"@odata.id": "/redfish/v1/Chassis/1/Power"},
    }
    thermal = {
        "Temperatures": [{
            "Name": "Inlet Temp", "ReadingCelsius": 22,
            "Status": {"Health": "OK", "State": "Enabled"},
        }],
        "Fans": [{
            "FanName": "Fan 1", "Reading": 5400, "ReadingUnits": "RPM",
            "Status": {"Health": "OK", "State": "Enabled"},
        }],
    }
    power = {
        "Voltages": [{
            "Name": "VCore", "ReadingVolts": 1.2,
            "Status": {"Health": "OK", "State": "Enabled"},
        }],
        "PowerControl": [{
            "Name": "System Power", "PowerConsumedWatts": 250,
        }],
    }

    def fake_get_optional(ref):
        return {
            "/redfish/v1/Chassis/1": chassis,
            "/redfish/v1/Chassis/1/Thermal": thermal,
            "/redfish/v1/Chassis/1/Power": power,
        }[ref]

    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", return_value=[sysres]), \
         patch.object(driver, "_get_optional", side_effect=fake_get_optional):
        readings = driver.get_sensors()

    kinds = {r.kind for r in readings}
    assert kinds == {"temperature", "fan", "voltage", "power"}
    temp = next(r for r in readings if r.kind == "temperature")
    assert temp.name == "Inlet Temp"
    assert temp.value == 22
    assert temp.units == "°C"
    fan = next(r for r in readings if r.kind == "fan")
    assert fan.value == 5400
    assert fan.units == "RPM"
    power_reading = next(r for r in readings if r.kind == "power")
    assert power_reading.value == 250
    assert power_reading.units == "W"


def test_redfish_get_sensors_skips_absent():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    sysres = {"Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}
    chassis = {"Thermal": {"@odata.id": "/redfish/v1/Chassis/1/Thermal"}}
    thermal = {
        "Temperatures": [{"Name": "Absent Temp", "Status": {"State": "Absent"}}],
    }

    def fake_get_optional(ref):
        return {
            "/redfish/v1/Chassis/1": chassis,
            "/redfish/v1/Chassis/1/Thermal": thermal,
        }[ref]

    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", return_value=[sysres]), \
         patch.object(driver, "_get_optional", side_effect=fake_get_optional):
        readings = driver.get_sensors()

    assert readings == []


# --- IPMI ----------------------------------------------------------------

def make_ipmi_driver():
    with patch("pyghmi.ipmi.command.Command", return_value=MagicMock()):
        return IPMIDriver("192.168.0.1", "admin", "admin")


def _sensor(name, stype, value, units, health=0):
    s = MagicMock()
    s.name = name
    s.type = stype
    s.value = value
    s.units = units
    s.health = health
    return s


def test_ipmi_get_sensors_maps_known_types():
    driver = make_ipmi_driver()
    driver.cmd.get_sensor_data.return_value = iter([
        _sensor("CPU1 Temp", "Temperature", 45, "degrees C"),
        _sensor("Fan1", "Fan", 3000, "RPM"),
        _sensor("12V", "Voltage", 12.1, "Volts", health=2),
        _sensor("Chassis Intrusion", "Physical Security", None, ""),
    ])

    readings = driver.get_sensors()

    kinds = [r.kind for r in readings]
    assert kinds == ["temperature", "fan", "voltage"]
    voltage = next(r for r in readings if r.kind == "voltage")
    assert voltage.status == "Critical"


def test_ipmi_get_sensors_wraps_errors():
    import pytest

    from netbox_bmc.drivers.base import BMCError

    driver = make_ipmi_driver()
    driver.cmd.get_sensor_data.side_effect = Exception("boom")

    with pytest.raises(BMCError):
        driver.get_sensors()
