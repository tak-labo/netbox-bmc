"""Tests for Intel AMT WS-MAN driver."""
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest

from netbox_bmc.drivers.amt import (
    IntelAmtDriver,
    _build_envelope,
    _parse_amt_hw_page,
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
# _parse_amt_hw_page
# ---------------------------------------------------------------------------

_DISK_HTML = """
<html><body>
<h2>Disk 1</h2>
<table>
<tr><td class=r1><p>Model</p></td><td class=r1>Samsung SSD 840 PRO Series</td></tr>
<tr><td class=r1><p>Serial number</p></td><td class=r1>S1AXNSAF513806P</td></tr>
<tr><td class=r1><p>Size</p></td><td class=r1>488386 MB</td></tr>
</table>
<h2>Disk 2</h2>
<table>
<tr><td class=r1><p>Model</p></td><td class=r1>Samsung SSD 980 250GB</td></tr>
<tr><td class=r1><p>Serial number</p></td><td class=r1>S64BNJ0R215887D</td></tr>
<tr><td class=r1><p>Size</p></td><td class=r1>238475 MB</td></tr>
</table>
</body></html>
"""


def test_parse_amt_hw_page_disks():
    disks = _parse_amt_hw_page(_DISK_HTML)
    assert len(disks) == 2
    assert disks[0]["Model"] == "Samsung SSD 840 PRO Series"
    assert disks[0]["Serial number"] == "S1AXNSAF513806P"
    assert disks[0]["Size"] == "488386 MB"
    assert disks[1]["Model"] == "Samsung SSD 980 250GB"
    assert disks[1]["Serial number"] == "S64BNJ0R215887D"


def test_collect_drives_uses_html():
    driver = make_driver()
    with patch.object(IntelAmtDriver, "_fetch_hw_page", return_value=_DISK_HTML):
        drives = driver._collect_drives()
    assert len(drives) == 2
    assert drives[0].name == "Samsung SSD 840 PRO Series"
    assert drives[0].serial == "S1AXNSAF513806P"
    assert "476GB" in drives[0].description
    assert drives[1].name == "Samsung SSD 980 250GB"
    assert drives[1].serial == "S64BNJ0R215887D"


# ---------------------------------------------------------------------------
# HTML fallback: sys / proc / mem
# ---------------------------------------------------------------------------

_SYS_HTML = """
<html><body>
<h2>Platform</h2>
<table>
<tr><td class=r1><p>Computer model</p></td><td class=r1>OptiPlex 7060</td></tr>
<tr><td class=r1><p>Manufacturer</p></td><td class=r1>Dell Inc.</td></tr>
<tr><td class=r1><p>Serial number</p></td><td class=r1>HCJT0W2</td></tr>
</table>
</body></html>
"""

_PROC_HTML = """
<html><body>
<h2 ID=processor>Processor 1</h2>
<table>
<tr><td class=r1><p>Manufacturer</p></td><td class=r1>Intel(R) Corporation</td></tr>
<tr><td class=r1><p>Version</p></td><td class=r1>Intel(R) Core(TM) i5-8500T CPU @ 2.10GHz</td></tr>
<tr><td class=r1><p>Maximum socket speed</p></td><td class=r1>4200 MHz</td></tr>
</table>
</body></html>
"""

_MEM_HTML = """
<html><body>
<h2>Module 1</h2>
<table>
<tr><td class=r1><p>Manufacturer</p></td><td class=r1>Kingston</td></tr>
<tr><td class=r1><p>Serial number</p></td><td class=r1>AABBCCDD</td></tr>
<tr><td class=r1><p>Size</p></td><td class=r1>8192 MB</td></tr>
<tr><td class=r1><p>Speed</p></td><td class=r1>2400 MHz</td></tr>
<tr><td class=r1><p>Part number</p></td><td class=r1>KVR24N17S8/8   </td></tr>
</table>
<h2>Module 2</h2>
<table>
<tr><td class=r1><p>Manufacturer</p></td><td class=r1>Kingston</td></tr>
<tr><td class=r1><p>Serial number</p></td><td class=r1>11223344</td></tr>
<tr><td class=r1><p>Size</p></td><td class=r1>8192 MB</td></tr>
<tr><td class=r1><p>Speed</p></td><td class=r1>2400 MHz</td></tr>
<tr><td class=r1><p>Part number</p></td><td class=r1>KVR24N17S8/8   </td></tr>
</table>
</body></html>
"""


def test_collect_system_html_fallback():
    """CIM_Chassis が空のとき hw-sys.htm から SystemInfo を返す。"""
    from netbox_bmc.drivers.base import BMCError

    driver = make_driver()

    def fake_post(self, action, resource_uri, body):
        raise BMCError("timeout")

    with (
        patch.object(IntelAmtDriver, "_post", fake_post),
        patch.object(IntelAmtDriver, "_fetch_hw_page", return_value=_SYS_HTML),
    ):
        info = driver._collect_system()
    assert info.model == "OptiPlex 7060"
    assert info.manufacturer == "Dell Inc."
    assert info.serial == "HCJT0W2"


def test_collect_processors_html_fallback():
    """CIM_Processor が空のとき hw-proc.htm から CPU Component を返す。"""
    from netbox_bmc.drivers.base import BMCError

    driver = make_driver()

    def fake_post(self, action, resource_uri, body):
        raise BMCError("timeout")

    with (
        patch.object(IntelAmtDriver, "_post", fake_post),
        patch.object(IntelAmtDriver, "_fetch_hw_page", return_value=_PROC_HTML),
    ):
        cpus = driver._collect_processors()
    assert len(cpus) == 1
    assert cpus[0].kind == "cpu"
    assert cpus[0].name == "CPU 0"
    assert "i5-8500T" in cpus[0].part_id
    assert "4GHz" in cpus[0].description


def test_collect_memory_html_fallback():
    """CIM_PhysicalMemory が空のとき hw-mem.htm からメモリ Component を返す。"""
    from netbox_bmc.drivers.base import BMCError

    driver = make_driver()

    def fake_post(self, action, resource_uri, body):
        raise BMCError("timeout")

    with (
        patch.object(IntelAmtDriver, "_post", fake_post),
        patch.object(IntelAmtDriver, "_fetch_hw_page", return_value=_MEM_HTML),
    ):
        mems = driver._collect_memory()
    assert len(mems) == 2
    assert mems[0].name == "Module 1"
    assert mems[0].serial == "AABBCCDD"
    assert "8GB" in mems[0].description
    assert "2400MHz" in mems[0].description
    assert mems[0].part_id == "KVR24N17S8/8"
    assert mems[1].serial == "11223344"


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
# get_inventory — full inventory
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

_CHASSIS_XML = (
    f'<p:CIM_Chassis xmlns:p="{_CIM}CIM_Chassis">'
    f"<p:Manufacturer>Dell Inc.</p:Manufacturer>"
    f"<p:Model>OptiPlex 7060</p:Model>"
    f"<p:SerialNumber>HCJT0W2</p:SerialNumber>"
    f"</p:CIM_Chassis>"
)

_DRIVE_XML = (
    f'<p:CIM_MediaAccessDevice xmlns:p="{_CIM}CIM_MediaAccessDevice">'
    f"<p:DeviceID>MEDIA DEV 0</p:DeviceID>"
    f"<p:MaxMediaSize>512110190</p:MaxMediaSize>"
    f"</p:CIM_MediaAccessDevice>"
)

_FAN_XML = (
    f'<p:CIM_Fan xmlns:p="{_CIM}CIM_Fan">'
    f"<p:DeviceID>Fan 0</p:DeviceID>"
    f"</p:CIM_Fan>"
)

_BIOS_XML = (
    f'<p:CIM_BIOSElement xmlns:p="{_CIM}CIM_BIOSElement">'
    f"<p:Version>1.32.0</p:Version>"
    f"<p:Manufacturer>Dell Inc.</p:Manufacturer>"
    f"</p:CIM_BIOSElement>"
)


def _full_inventory_fake_post(action, resource_uri, body):
    """全 CIM クラスに対応する fake_post (staticmethod 用)。"""
    enum_resp = _make_enumerate_response("ctx-1")
    if "Identify" in action:
        return ET.fromstring(_make_identify_response())
    if action.split("/")[-1] == "Enumerate":
        return ET.fromstring(enum_resp)
    # Pull — resource_uri で振り分け
    dispatch = {
        "CIM_Chassis": _CHASSIS_XML,
        "CIM_Processor": _CPU_XML,
        "CIM_PhysicalMemory": _MEM_XML,
        "CIM_MediaAccessDevice": _DRIVE_XML,
        "CIM_Fan": _FAN_XML,
        "CIM_BIOSElement": _BIOS_XML,
    }
    for cls, xml in dispatch.items():
        if cls in resource_uri:
            return ET.fromstring(_make_pull_response(cls, xml, end=True))
    return ET.fromstring(_make_pull_response("Unknown", "", end=True))


def test_get_inventory_cpu_and_memory():
    driver = make_driver()

    with patch.object(IntelAmtDriver, "_post", lambda self, *a, **kw: _full_inventory_fake_post(*a, **kw)):
        result = driver.get_inventory()

    assert result.vendor == "Intel AMT"
    assert result.protocol == "wsman"
    assert result.system.serial == "HCJT0W2"
    assert result.system.model == "OptiPlex 7060"
    assert result.system.manufacturer == "Dell Inc."

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

    drive_components = [c for c in result.components if c.kind == "drive"]
    assert len(drive_components) == 1
    assert drive_components[0].name == "MEDIA DEV 0"
    assert "488GB" in drive_components[0].description

    fan_components = [c for c in result.components if c.kind == "fan"]
    assert len(fan_components) == 1
    assert fan_components[0].name == "Fan 0"

    fw_components = [c for c in result.components if c.kind == "firmware"]
    # AMT firmware + BIOS firmware
    assert any(c.firmware == "12.0.45" and c.name == "AMT" for c in fw_components)
    assert any(c.firmware == "1.32.0" and c.name == "BIOS" for c in fw_components)


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
