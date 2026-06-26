"""Tests for Intel AMT WS-MAN driver."""
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest

from netbox_bmc.drivers.amt import (
    IntelAmtDriver,
    _build_envelope,
    _parse_items,
    _xml_text,
    probe_amt,
)

_CIM = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/"
_WSEN = "http://schemas.xmlsoap.org/ws/2004/09/enumeration"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_pull_response(cim_class: str, items_xml: str, end: bool = True) -> str:
    end_tag = "<wsen:EndOfSequence/>" if end else ""
    return (
        f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
        f' xmlns:wsen="{_WSEN}">'
        f"<s:Body>"
        f"<wsen:PullResponse>"
        f"<wsen:Items>{items_xml}</wsen:Items>"
        f"{end_tag}"
        f"</wsen:PullResponse>"
        f"</s:Body>"
        f"</s:Envelope>"
    )


def _make_enumerate_response(ctx: str = "ctx-1") -> str:
    return (
        f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
        f' xmlns:wsen="{_WSEN}">'
        f"<s:Body>"
        f"<wsen:EnumerateResponse>"
        f"<wsen:EnumerationContext>{ctx}</wsen:EnumerationContext>"
        f"</wsen:EnumerateResponse>"
        f"</s:Body>"
        f"</s:Envelope>"
    )


def _make_identify_response(version: str = "12.0.45") -> str:
    ns = "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd"
    return (
        f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
        f' xmlns:wsmid="{ns}">'
        f"<s:Body>"
        f"<wsmid:IdentifyResponse>"
        f"<wsmid:ProductVendor>Intel Corporation</wsmid:ProductVendor>"
        f"<wsmid:ProductVersion>{version}</wsmid:ProductVersion>"
        f"</wsmid:IdentifyResponse>"
        f"</s:Body>"
        f"</s:Envelope>"
    )


def make_driver():
    return IntelAmtDriver("192.168.0.10", "admin", "P@ssw0rd")


# ---------------------------------------------------------------------------
# unit helpers
# ---------------------------------------------------------------------------

def test_build_envelope_contains_action():
    xml = _build_envelope("http://test/Action", "http://test/uri", "<Body/>")
    assert "http://test/Action" in xml
    assert "<Body/>" in xml


def test_xml_text_found():
    ns = f"{_CIM}CIM_Processor"
    elem = ET.fromstring(
        f'<p:CIM_Processor xmlns:p="{_CIM}CIM_Processor">'
        f"<p:Name>Intel Core i7</p:Name>"
        f"</p:CIM_Processor>"
    )
    assert _xml_text(elem, "Name", ns) == "Intel Core i7"


def test_xml_text_missing():
    ns = f"{_CIM}CIM_Processor"
    elem = ET.fromstring(f'<p:CIM_Processor xmlns:p="{_CIM}CIM_Processor"/>')
    assert _xml_text(elem, "Name", ns) == ""


def test_parse_items_returns_children():
    xml = (
        f'<root xmlns:wsen="{_WSEN}">'
        f"<wsen:Items><Child1/><Child2/></wsen:Items>"
        f"</root>"
    )
    items = _parse_items(ET.fromstring(xml))
    assert len(items) == 2


def test_parse_items_no_items_tag():
    items = _parse_items(ET.fromstring("<root/>"))
    assert items == []


# ---------------------------------------------------------------------------
# probe_amt
# ---------------------------------------------------------------------------

def test_probe_amt_returns_true_on_200_with_wsman():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<IdentifyResponse>wsman stuff</IdentifyResponse>"
    with patch("netbox_bmc.drivers.amt.requests.post", return_value=mock_resp):
        assert probe_amt("192.168.0.10") is True


def test_probe_amt_returns_true_on_401():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "wsman digest required"
    with patch("netbox_bmc.drivers.amt.requests.post", return_value=mock_resp):
        assert probe_amt("192.168.0.10") is True


def test_probe_amt_returns_false_on_connection_error():
    import requests as req
    with patch("netbox_bmc.drivers.amt.requests.post",
               side_effect=req.RequestException("timeout")):
        assert probe_amt("192.168.0.10") is False


def test_probe_amt_returns_false_on_404():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "not found"
    with patch("netbox_bmc.drivers.amt.requests.post", return_value=mock_resp):
        assert probe_amt("192.168.0.10") is False


# ---------------------------------------------------------------------------
# get_inventory — CPU + Memory + Firmware
# ---------------------------------------------------------------------------

_CPU_XML = (
    f'<p:CIM_Processor xmlns:p="{_CIM}CIM_Processor">'
    f"<p:DeviceID>CPU 0</p:DeviceID>"
    f"<p:Name>Intel Core i7-12700</p:Name>"
    f"<p:Manufacturer>Intel Corporation</p:Manufacturer>"
    f"<p:NumberOfCores>12</p:NumberOfCores>"
    f"<p:NumberOfLogicalProcessors>20</p:NumberOfLogicalProcessors>"
    f"<p:MaxClockSpeed>4900</p:MaxClockSpeed>"
    f"</p:CIM_Processor>"
)

_MEM_XML = (
    f'<p:CIM_PhysicalMemory xmlns:p="{_CIM}CIM_PhysicalMemory">'
    f"<p:Tag>DIMM 0</p:Tag>"
    f"<p:Capacity>{16 * 1024 ** 3}</p:Capacity>"
    f"<p:Speed>3200</p:Speed>"
    f"<p:PartNumber>KVR32N22D8/16</p:PartNumber>"
    f"<p:SerialNumber>AABBCCDD</p:SerialNumber>"
    f"<p:Manufacturer>Kingston</p:Manufacturer>"
    f"</p:CIM_PhysicalMemory>"
)


def _make_fake_post(*action_responses: tuple[str, str]):
    """action キーワードでレスポンスを振り分ける fake_post を返す。"""
    mapping = {key: ET.fromstring(xml) for key, xml in action_responses}

    def fake_post(self, action, resource_uri, body):
        for key, elem in mapping.items():
            if key in action or key in resource_uri:
                return elem
        # フォールバック: EndOfSequence 付き空 Pull
        return ET.fromstring(_make_pull_response("Unknown", "", end=True))

    return fake_post


def test_get_inventory_cpu_and_memory():
    driver = make_driver()

    # _enumerate の Enumerate→Pull の 2 コールに対応するため、
    # resource_uri で振り分ける専用 fake_post を使う。
    _IDENTIFY = "Identify"
    _ENUM_CPU  = "Enumerate"   # Enumerate は resource_uri で区別
    _PULL_CPU  = "Pull"

    sys_empty_pull = _make_pull_response("CIM_ComputerSystemPackage", "", end=True)
    cpu_pull       = _make_pull_response("CIM_Processor", _CPU_XML, end=True)
    mem_pull       = _make_pull_response("CIM_PhysicalMemory", _MEM_XML, end=True)
    enum_resp      = _make_enumerate_response("ctx-1")

    def fake_post(self, action, resource_uri, body):
        if "Identify" in action:
            return ET.fromstring(_make_identify_response())
        action_tail = action.split("/")[-1]
        if action_tail == "Enumerate":
            return ET.fromstring(enum_resp)
        # Pull — resource_uri で振り分け
        if "CIM_Processor" in resource_uri:
            return ET.fromstring(cpu_pull)
        if "CIM_PhysicalMemory" in resource_uri:
            return ET.fromstring(mem_pull)
        return ET.fromstring(sys_empty_pull)

    with patch.object(IntelAmtDriver, "_post", fake_post):
        result = driver.get_inventory()

    assert result.vendor == "Intel AMT"
    assert result.protocol == "wsman"

    cpu_components = [c for c in result.components if c.kind == "cpu"]
    assert len(cpu_components) == 1
    cpu = cpu_components[0]
    assert cpu.name == "CPU 0"
    assert cpu.manufacturer == "Intel Corporation"
    assert "12C" in cpu.description
    assert "4GHz" in cpu.description

    mem_components = [c for c in result.components if c.kind == "memory"]
    assert len(mem_components) == 1
    mem = mem_components[0]
    assert mem.name == "DIMM 0"
    assert mem.description == "16GB 3200MHz"
    assert mem.serial == "AABBCCDD"

    fw_components = [c for c in result.components if c.kind == "firmware"]
    assert len(fw_components) == 1
    assert fw_components[0].firmware == "12.0.45"


def test_get_inventory_graceful_on_enumerate_error():
    """_enumerate が BMCError を上げても get_inventory は空リストを返す。"""
    from netbox_bmc.drivers.base import BMCError

    driver = make_driver()

    def fake_post(self, action, resource_uri, body):
        if "Identify" in action:
            return ET.fromstring(_make_identify_response("11.8.55"))
        raise BMCError("timeout")

    with patch.object(IntelAmtDriver, "_post", fake_post):
        result = driver.get_inventory()

    assert result.components == [] or all(c.kind == "firmware" for c in result.components)


# ---------------------------------------------------------------------------
# power state
# ---------------------------------------------------------------------------

def _power_fake_post(power_state_value: str):
    ns = f"{_CIM}CIM_AssociatedPowerManagementService"
    state_xml = (
        f'<p:CIM_AssociatedPowerManagementService xmlns:p="{ns}">'
        f"<p:PowerState>{power_state_value}</p:PowerState>"
        f"</p:CIM_AssociatedPowerManagementService>"
    )

    def fake_post(self, action, resource_uri, body):
        action_tail = action.split("/")[-1]
        if action_tail == "Enumerate":
            return ET.fromstring(_make_enumerate_response("ctx-pwr"))
        return ET.fromstring(_make_pull_response(
            "CIM_AssociatedPowerManagementService", state_xml, end=True))

    return fake_post


def test_get_power_state_on():
    driver = make_driver()
    with patch.object(IntelAmtDriver, "_post", _power_fake_post("2")):
        assert driver.get_power_state() == "On"


def test_get_power_state_off():
    driver = make_driver()
    with patch.object(IntelAmtDriver, "_post", _power_fake_post("8")):
        assert driver.get_power_state() == "Off"


def test_set_power_on():
    driver = make_driver()
    posted = []

    def fake_post(self, action, resource_uri, body):
        posted.append((action, body))
        return ET.fromstring("<s:Envelope xmlns:s='http://www.w3.org/2003/05/soap-envelope'><s:Body/></s:Envelope>")

    with patch.object(IntelAmtDriver, "_post", fake_post):
        driver.set_power("on")

    assert any("RequestPowerStateChange" in a for a, _ in posted)
    assert any("<p:PowerState>2</p:PowerState>" in b for _, b in posted)


def test_set_power_invalid_action():
    from netbox_bmc.drivers.base import BMCError
    driver = make_driver()
    with pytest.raises(BMCError, match="Unknown power action"):
        driver.set_power("hibernate")


# ---------------------------------------------------------------------------
# detect_and_build wsman protocol
# ---------------------------------------------------------------------------

def test_detect_and_build_wsman_protocol():
    """protocol='wsman' は IntelAmtDriver を直接返す。"""
    from netbox_bmc.drivers.base import detect_and_build

    with patch("netbox_bmc.drivers.amt.IntelAmtDriver.__init__", return_value=None):
        driver = detect_and_build("192.168.0.10", "admin", "pass", protocol="wsman")
    assert isinstance(driver, IntelAmtDriver)


def test_detect_and_build_auto_falls_through_to_amt():
    """auto モードで Redfish が失敗し AMT probe が成功すれば IntelAmtDriver を返す。"""
    from netbox_bmc.drivers.base import detect_and_build

    with (
        patch("netbox_bmc.drivers.redfish.probe_redfish", return_value=False),
        patch("netbox_bmc.drivers.amt.probe_amt", return_value=True),
        patch("netbox_bmc.drivers.amt.IntelAmtDriver.__init__", return_value=None),
    ):
        driver = detect_and_build("192.168.0.10", "admin", "pass", protocol="auto")
    assert isinstance(driver, IntelAmtDriver)
