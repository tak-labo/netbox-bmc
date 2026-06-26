"""
Intel AMT (Active Management Technology) WS-MAN ドライバ。

WS-MAN (SOAP/XML over HTTP) を使い、追加ライブラリなし (requests + stdlib xml) で
CPU / Memory / AMT ファームウェアバージョンを取得する。

対応: AMT 6.0 以降 (vPro 第 1 世代以降)
ポート: 16992 (HTTP) / 16993 (HTTPS)
認証: HTTP Digest
"""
from __future__ import annotations

import logging
import uuid
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import requests
import urllib3
from requests.auth import HTTPDigestAuth

from ..inventory import Component, InventoryResult, SystemInfo
from .base import BaseDriver, BMCError

if TYPE_CHECKING:
    pass

logger = logging.getLogger("netbox_bmc.amt")

# WS-MAN XML 名前空間
_NS = {
    "s":      "http://www.w3.org/2003/05/soap-envelope",
    "wsa":    "http://schemas.xmlsoap.org/ws/2004/08/addressing",
    "wsman":  "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd",
    "wsen":   "http://schemas.xmlsoap.org/ws/2004/09/enumeration",
    "wsmid":  "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd",
}

_CIM = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/"
_ACTION_IDENTIFY = "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity/Identify"
_ACTION_ENUMERATE = "http://schemas.xmlsoap.org/ws/2004/09/enumeration/Enumerate"
_ACTION_PULL = "http://schemas.xmlsoap.org/ws/2004/09/enumeration/Pull"
_ACTION_POWER = (
    "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/"
    "CIM_PowerManagementService/RequestPowerStateChange"
)
_ANON = "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous"

# CIM 電源状態マップ
_POWER_STATE = {
    "on":    2,
    "off":   8,   # Power Off - Hard
    "soft":  12,  # Soft Off (ACPI S5)
    "cycle": 9,   # Power Cycle (Off-Soft)
    "reset": 10,  # Master Bus Reset
}

AMT_DEFAULT_PORT = 16993
AMT_HTTP_PORT = 16992

_IDENTIFY_BODY = "<wsmid:Identify/>"
_IDENTIFY_URI = "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd"


def _probe_url(url: str, timeout: int, verify: bool) -> bool:
    import warnings
    try:
        with warnings.catch_warnings():
            if not verify:
                warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            r = requests.post(
                url,
                data=_build_envelope(_ACTION_IDENTIFY, _IDENTIFY_URI, _IDENTIFY_BODY),
                headers={"Content-Type": "application/soap+xml;charset=UTF-8"},
                timeout=timeout,
                verify=verify,
            )
        return r.status_code in (200, 401) and "wsman" in r.text.lower()
    except requests.RequestException:
        return False


def probe_amt(address: str, timeout: int = 5, verify_ssl: bool = False) -> bool:
    """AMT WS-MAN の存在確認。HTTPS (16993) → HTTP (16992) の順で probe する。"""
    return (
        _probe_url(f"https://{address}:{AMT_DEFAULT_PORT}/wsman", timeout, verify_ssl)
        or _probe_url(f"http://{address}:{AMT_HTTP_PORT}/wsman", timeout, verify_ssl)
    )


def _detect_scheme_and_port(address: str, timeout: int = 5,
                             verify_ssl: bool = False) -> tuple[str, int]:
    """接続可能なスキームとポートを返す。デフォルトは https:16993。"""
    if _probe_url(f"https://{address}:{AMT_DEFAULT_PORT}/wsman", timeout, verify_ssl):
        return "https", AMT_DEFAULT_PORT
    if _probe_url(f"http://{address}:{AMT_HTTP_PORT}/wsman", timeout, verify_ssl):
        return "http", AMT_HTTP_PORT
    return "https", AMT_DEFAULT_PORT


def _build_envelope(action: str, resource_uri: str, body: str,
                    endpoint: str = _ANON) -> str:
    msg_id = f"uuid:{uuid.uuid4()}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope '
        'xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd" '
        'xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration" '
        'xmlns:wsmid="http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd">'
        "<s:Header>"
        f"<wsa:Action>{action}</wsa:Action>"
        f"<wsa:To>{endpoint}</wsa:To>"
        f"<wsman:ResourceURI>{resource_uri}</wsman:ResourceURI>"
        f"<wsa:MessageID>{msg_id}</wsa:MessageID>"
        "<wsa:ReplyTo>"
        f"<wsa:Address>{_ANON}</wsa:Address>"
        "</wsa:ReplyTo>"
        "</s:Header>"
        f"<s:Body>{body}</s:Body>"
        "</s:Envelope>"
    )


def _xml_text(elem: ET.Element, tag: str, ns: str = _CIM + "CIM_Processor") -> str:
    """ns:tag のテキストを返す。見つからなければ空文字。"""
    # タグは {namespace}localname 形式
    found = elem.find(f"{{{ns}}}{tag}")
    if found is not None and found.text:
        return found.text.strip()
    return ""


def _parse_items(root: ET.Element) -> list[ET.Element]:
    """EnumerateResponse / PullResponse から Items 内の要素リストを返す。"""
    items = root.find(".//{http://schemas.xmlsoap.org/ws/2004/09/enumeration}Items")
    if items is None:
        return []
    return list(items)


class IntelAmtDriver(BaseDriver):
    protocol = "wsman"
    DEFAULT_PORT = AMT_DEFAULT_PORT

    def __init__(self, address: str, username: str, password: str,
                 port: int | None = None, verify_ssl: bool = False,
                 timeout: int = 15):
        # port 未指定時はプローブして HTTP/HTTPS を自動選択
        if port:
            scheme = "http" if port == AMT_HTTP_PORT else "https"
            resolved_port = port
        else:
            scheme, resolved_port = _detect_scheme_and_port(address, timeout=5,
                                                             verify_ssl=verify_ssl)
        super().__init__(address, username, password,
                         port=resolved_port,
                         verify_ssl=verify_ssl, timeout=timeout)
        self._endpoint = f"{scheme}://{self.address}:{self.port}/wsman"
        self._session = requests.Session()
        self._session.auth = HTTPDigestAuth(self.username, self.password)
        self._session.verify = self.verify_ssl
        self._session.headers.update({
            "Content-Type": "application/soap+xml;charset=UTF-8",
        })

    # --- SOAP ヘルパ ----------------------------------------------------------

    def _suppress_ssl_warnings(self):
        import warnings
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            with warnings.catch_warnings():
                if not self.verify_ssl:
                    warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
                yield

        return _cm()

    def _post(self, action: str, resource_uri: str, body: str) -> ET.Element:
        xml_body = _build_envelope(action, resource_uri, body, self._endpoint)
        try:
            with self._suppress_ssl_warnings():
                r = self._session.post(self._endpoint, data=xml_body,
                                       timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            raise BMCError(f"WS-MAN {action.split('/')[-1]} failed: {e}") from e
        try:
            return ET.fromstring(r.text)
        except ET.ParseError as e:
            raise BMCError(f"WS-MAN XML parse error: {e}") from e

    def _enumerate(self, cim_class: str) -> list[ET.Element]:
        """CIM クラスを Enumerate + Pull して要素リストを返す。"""
        resource_uri = f"{_CIM}{cim_class}"
        # Enumerate
        root = self._post(_ACTION_ENUMERATE, resource_uri,
                          "<wsen:Enumerate/>")
        ctx_elem = root.find(".//{http://schemas.xmlsoap.org/ws/2004/09/enumeration}EnumerationContext")
        if ctx_elem is None:
            # 一部実装は EnumerateResponse に Items を直接含む
            return _parse_items(root)

        ctx = ctx_elem.text or ""
        results = []
        # Pull ループ
        while ctx:
            pull_body = (
                f"<wsen:Pull>"
                f"<wsen:EnumerationContext>{ctx}</wsen:EnumerationContext>"
                f"<wsen:MaxElements>100</wsen:MaxElements>"
                f"</wsen:Pull>"
            )
            pull_root = self._post(_ACTION_PULL, resource_uri, pull_body)
            results.extend(_parse_items(pull_root))
            end = pull_root.find(
                ".//{http://schemas.xmlsoap.org/ws/2004/09/enumeration}EndOfSequence"
            )
            if end is not None:
                break
            next_ctx = pull_root.find(
                ".//{http://schemas.xmlsoap.org/ws/2004/09/enumeration}EnumerationContext"
            )
            ctx = next_ctx.text if next_ctx is not None and next_ctx.text else ""

        return results

    def _identify(self) -> dict:
        resource_uri = "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd"
        root = self._post(_ACTION_IDENTIFY, resource_uri, "<wsmid:Identify/>")
        ns = "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd"
        return {
            "product_vendor": (root.findtext(f".//{{{ns}}}ProductVendor") or "").strip(),
            "product_version": (root.findtext(f".//{{{ns}}}ProductVersion") or "").strip(),
        }

    # --- インベントリ ---------------------------------------------------------

    def get_inventory(self) -> InventoryResult:
        try:
            identity = self._identify()
        except BMCError:
            identity = {}

        system = self._collect_system()
        components: list[Component] = []
        components += self._collect_processors()
        components += self._collect_memory()
        components += self._collect_drives()
        components += self._collect_fans()
        components += self._collect_bios()
        if identity.get("product_version"):
            components.append(Component(
                kind="firmware",
                name="AMT",
                description="Intel AMT",
                firmware=identity["product_version"],
                source_path=self._endpoint,
            ))

        return InventoryResult(
            system=system,
            components=components,
            vendor="Intel AMT",
            protocol=self.protocol,
        )

    def _collect_system(self) -> SystemInfo:
        # CIM_Chassis: SerialNumber, Model, Manufacturer が AMT 12 でも取得可能
        try:
            items = self._enumerate("CIM_Chassis")
        except BMCError:
            return SystemInfo()
        ns = f"{_CIM}CIM_Chassis"
        for item in items:
            return SystemInfo(
                manufacturer=_xml_text(item, "Manufacturer", ns),
                model=_xml_text(item, "Model", ns),
                serial=_xml_text(item, "SerialNumber", ns),
            )
        return SystemInfo()

    def _collect_processors(self) -> list[Component]:
        out = []
        try:
            items = self._enumerate("CIM_Processor")
        except BMCError:
            return out
        ns = f"{_CIM}CIM_Processor"
        for item in items:
            name = _xml_text(item, "DeviceID", ns) or _xml_text(item, "Name", ns) or "CPU"
            cores = _xml_text(item, "NumberOfCores", ns)
            threads = _xml_text(item, "NumberOfLogicalProcessors", ns)
            speed = _xml_text(item, "MaxClockSpeed", ns)
            mfr = _xml_text(item, "Manufacturer", ns)
            model = _xml_text(item, "Name", ns)
            desc_parts = []
            if cores:
                desc_parts.append(f"{cores}C")
            if threads:
                desc_parts[-1] += f"/{threads}T" if desc_parts else f"{threads}T"
            if speed:
                desc_parts.append(f"{int(speed) // 1000}GHz")
            out.append(Component(
                kind="cpu",
                name=name,
                manufacturer=mfr,
                part_id=model,
                description=" ".join(desc_parts),
                extra={
                    "cores": int(cores) if cores else 0,
                    "speed_mhz": int(speed) if speed else 0,
                },
                source_path=self._endpoint,
            ))
        return out

    def _collect_memory(self) -> list[Component]:
        out = []
        try:
            items = self._enumerate("CIM_PhysicalMemory")
        except BMCError:
            return out
        ns = f"{_CIM}CIM_PhysicalMemory"
        for item in items:
            tag = _xml_text(item, "Tag", ns) or _xml_text(item, "DeviceLocator", ns) or "DIMM"
            cap_bytes = _xml_text(item, "Capacity", ns)
            # Speed=0 の場合は ConfiguredMemoryClockSpeed / MaxMemorySpeed を使う
            _speed_raw = _xml_text(item, "Speed", ns)
            speed = (_speed_raw if _speed_raw and _speed_raw != "0" else None) or (
                _xml_text(item, "ConfiguredMemoryClockSpeed", ns)
                or _xml_text(item, "MaxMemorySpeed", ns)
            )
            part = _xml_text(item, "PartNumber", ns)
            serial = _xml_text(item, "SerialNumber", ns)
            mfr = _xml_text(item, "Manufacturer", ns)
            cap_gb = int(cap_bytes) // (1024 ** 3) if cap_bytes else 0
            desc = f"{cap_gb}GB" if cap_gb else ""
            if speed:
                desc += f" {speed}MHz"
            out.append(Component(
                kind="memory",
                name=tag,
                manufacturer=mfr,
                part_id=part,
                serial=serial,
                description=desc.strip(),
                extra={"capacity_mib": cap_gb * 1024 if cap_gb else 0},
                source_path=self._endpoint,
            ))
        return out

    def _collect_drives(self) -> list[Component]:
        # AMT 12.0 ではモデル名・シリアルは WS-MAN に公開されない。
        # CIM_MediaAccessDevice から MaxMediaSize (KB) のみ取得する。
        out = []
        try:
            items = self._enumerate("CIM_MediaAccessDevice")
        except BMCError:
            return out
        ns = f"{_CIM}CIM_MediaAccessDevice"
        for idx, item in enumerate(items):
            dev_id = _xml_text(item, "DeviceID", ns) or f"MEDIA DEV {idx}"
            size_kb = _xml_text(item, "MaxMediaSize", ns)
            size_gb = int(size_kb) // (1024 * 1024) if size_kb else 0
            desc = f"{size_gb}GB" if size_gb else ""
            out.append(Component(
                kind="drive",
                name=dev_id,
                description=desc,
                extra={"size_gb": size_gb},
                source_path=self._endpoint,
            ))
        return out

    def _collect_fans(self) -> list[Component]:
        out = []
        try:
            items = self._enumerate("CIM_Fan")
        except BMCError:
            return out
        ns = f"{_CIM}CIM_Fan"
        for idx, item in enumerate(items):
            name = _xml_text(item, "DeviceID", ns) or _xml_text(item, "Name", ns) or f"Fan {idx}"
            out.append(Component(
                kind="fan",
                name=name,
                source_path=self._endpoint,
            ))
        return out

    def _collect_bios(self) -> list[Component]:
        out = []
        try:
            items = self._enumerate("CIM_BIOSElement")
        except BMCError:
            return out
        ns = f"{_CIM}CIM_BIOSElement"
        for item in items:
            version = _xml_text(item, "Version", ns)
            mfr = _xml_text(item, "Manufacturer", ns)
            if version:
                out.append(Component(
                    kind="firmware",
                    name="BIOS",
                    manufacturer=mfr,
                    description="System BIOS",
                    firmware=version,
                    source_path=self._endpoint,
                ))
            break
        return out

    # --- 電源操作 ------------------------------------------------------------

    def get_power_state(self) -> str:
        try:
            items = self._enumerate("CIM_AssociatedPowerManagementService")
        except BMCError:
            return "Unknown"
        ns = f"{_CIM}CIM_AssociatedPowerManagementService"
        for item in items:
            state_str = _xml_text(item, "PowerState", ns)
            state_map = {"2": "On", "6": "Off", "8": "Off", "3": "Standby"}
            return state_map.get(state_str, f"Unknown({state_str})")
        return "Unknown"

    def set_power(self, action: str) -> None:
        state = _POWER_STATE.get(action)
        if state is None:
            raise BMCError(f"Unknown power action: {action}")
        resource_uri = f"{_CIM}CIM_PowerManagementService"
        body = (
            f'<p:RequestPowerStateChange_INPUT '
            f'xmlns:p="{resource_uri}">'
            f"<p:PowerState>{state}</p:PowerState>"
            f'<p:ManagedElement>'
            f'<wsa:Address>{_ANON}</wsa:Address>'
            f'<wsa:ReferenceParameters>'
            f'<wsman:ResourceURI>{_CIM}CIM_ComputerSystem</wsman:ResourceURI>'
            f'</wsa:ReferenceParameters>'
            f'</p:ManagedElement>'
            f"</p:RequestPowerStateChange_INPUT>"
        )
        try:
            self._post(_ACTION_POWER, resource_uri, body)
        except BMCError as e:
            raise BMCError(f"AMT power action failed: {e}") from e

    def close(self):
        self._session.close()
