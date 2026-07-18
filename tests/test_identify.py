"""Tests for Identify LED control (set_identify())."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from netbox_bmc.drivers.base import BMCError
from netbox_bmc.drivers.ipmi import IPMIDriver
from netbox_bmc.drivers.redfish import RedfishDriver

# --- Redfish -----------------------------------------------------------

def make_redfish_driver():
    with patch.object(RedfishDriver, "_login"):
        return RedfishDriver("bmc.example.com", "admin", "pass")


def test_redfish_set_identify_on_via_location_indicator():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    systems = [{"Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}]

    patch_response = MagicMock(status_code=200)
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", return_value=systems), \
         patch.object(driver, "_get_etag", return_value=None), \
         patch.object(driver.session, "patch", return_value=patch_response) as mock_patch:
        driver.set_identify(True)

    mock_patch.assert_called_once()
    _, kwargs = mock_patch.call_args
    assert kwargs["json"] == {"LocationIndicatorActive": True}


def test_redfish_set_identify_sends_if_match_etag():
    """Some implementations (iDRAC) require If-Match or return 428 Precondition Required."""
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    systems = [{"Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}]

    patch_response = MagicMock(status_code=200)
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", return_value=systems), \
         patch.object(driver, "_get_etag", return_value='"abc123"'), \
         patch.object(driver.session, "patch", return_value=patch_response) as mock_patch:
        driver.set_identify(True)

    _, kwargs = mock_patch.call_args
    assert kwargs["headers"] == {"If-Match": '"abc123"'}


def test_redfish_set_identify_falls_back_to_indicator_led():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    systems = [{"Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}]

    rejected = MagicMock(status_code=400, text="Bad property")
    ok = MagicMock(status_code=200)
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", return_value=systems), \
         patch.object(driver, "_get_etag", return_value=None), \
         patch.object(driver.session, "patch", side_effect=[rejected, ok]) as mock_patch:
        driver.set_identify(False)

    assert mock_patch.call_count == 2
    second_call_kwargs = mock_patch.call_args_list[1][1]
    assert second_call_kwargs["json"] == {"IndicatorLED": "Off"}


def test_redfish_get_etag_prefers_http_header():
    driver = make_redfish_driver()
    resp = MagicMock(status_code=200, headers={"ETag": '"http-etag"'})
    with patch.object(driver.session, "get", return_value=resp):
        assert driver._get_etag("/redfish/v1/Chassis/1") == '"http-etag"'


def test_redfish_get_etag_falls_back_to_odata_etag():
    driver = make_redfish_driver()
    resp = MagicMock(status_code=200, headers={})
    resp.json.return_value = {"@odata.etag": '"body-etag"'}
    with patch.object(driver.session, "get", return_value=resp):
        assert driver._get_etag("/redfish/v1/Chassis/1") == '"body-etag"'


def test_redfish_get_etag_returns_none_on_failure():
    driver = make_redfish_driver()
    with patch.object(driver.session, "get", side_effect=requests.RequestException("boom")):
        assert driver._get_etag("/redfish/v1/Chassis/1") is None


def test_redfish_set_identify_no_chassis_raises():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    systems = [{"Links": {}}]
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", return_value=systems):
        with pytest.raises(BMCError):
            driver.set_identify(True)


# --- IPMI ----------------------------------------------------------------

def make_ipmi_driver():
    with patch("pyghmi.ipmi.command.Command", return_value=MagicMock()):
        return IPMIDriver("192.168.0.1", "admin", "admin")


def test_ipmi_set_identify_delegates_to_pyghmi():
    driver = make_ipmi_driver()
    driver.set_identify(True)
    driver.cmd.set_identify.assert_called_once_with(on=True)


def test_ipmi_set_identify_wraps_errors():
    driver = make_ipmi_driver()
    driver.cmd.set_identify.side_effect = Exception("unsupported")
    with pytest.raises(BMCError):
        driver.set_identify(True)
