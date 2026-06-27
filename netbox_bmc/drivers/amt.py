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
import re
import uuid
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
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
        # 401 = auth required = WS-MAN endpoint confirmed (body may not contain "wsman")
        if r.status_code == 401:
            return True
        return r.status_code == 200 and "wsman" in r.text.lower()
    except requests.RequestException:
        return False


def probe_amt(address: str, timeout: int = 5, verify_ssl: bool = False) -> bool:
    """AMT WS-MAN の存在確認。HTTP (16992) → HTTPS (16993) の順で probe する。"""
    return (
        _probe_url(f"http://{address}:{AMT_HTTP_PORT}/wsman", timeout, verify_ssl)
        or _probe_url(f"https://{address}:{AMT_DEFAULT_PORT}/wsman", timeout, verify_ssl)
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


class _HwPageParser(HTMLParser):
    """AMT hw-*.htm の class=r1 テーブルから key-value ペアを抽出する。

    各セクション (<h2>) をキーとし、その下の r1 ペアを dict のリストとして返す。
    """

    def __init__(self):
        super().__init__()
        self._in_r1 = False
        self._buf = ""
        self._pair: list[str] = []
        self._section = "__default__"
        self.sections: dict[str, list[dict[str, str]]] = {}
        self._current_rows: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "")
        if tag == "h2":
            self._flush_section()
        if tag == "td" and cls == "r1":
            self._in_r1 = True
            self._buf = ""

    def handle_endtag(self, tag):
        if tag == "h2":
            # section name comes from the text accumulated in _buf before h2 ends
            pass
        if tag == "td" and self._in_r1:
            self._in_r1 = False
            self._pair.append(self._buf.strip())
            if len(self._pair) == 2:
                k, v = self._pair
                k = k.strip()
                v = v.strip()
                if k:
                    self._current_rows.append({k: v})
                self._pair = []

    def handle_data(self, data):
        if self._in_r1:
            self._buf += data

    def _flush_section(self):
        if self._current_rows:
            self.sections.setdefault(self._section, []).extend(self._current_rows)
            self._current_rows = []

    def close(self):
        self._flush_section()
        super().close()

    def flat(self) -> dict[str, str]:
        """全セクションを 1 つの dict にまとめて返す（最初の値優先）。"""
        out: dict[str, str] = {}
        for rows in self.sections.values():
            for row in rows:
                for k, v in row.items():
                    out.setdefault(k, v)
        return out


def _base_clock_mhz_from_model(model_name: str) -> int:
    """モデル名の '@ X.XXGHz' からベースクロックを MHz で返す。見つからなければ 0。"""
    m = re.search(r'@\s*([\d.]+)\s*GHz', model_name, re.IGNORECASE)
    return int(float(m.group(1)) * 1000) if m else 0


def _fmt_ghz(speed_mhz: int) -> str:
    """1900 → '1.9GHz', 2100 → '2.1GHz', 3200 → '3.2GHz'"""
    return f"{speed_mhz / 1000:.2f}".rstrip("0").rstrip(".") + "GHz"


def _parse_amt_hw_page(html: str) -> list[dict[str, str]]:
    """hw-*.htm から class=r1 の key-value ペアをリストで返す。

    ページ内に複数のセクション（Disk 1 / Disk 2 など）が含まれる場合も
    各セクションを 1 つの dict にしてリストで返す。
    """
    # セクション区切りは <h2> タグ。Disk ページは Disk 1, Disk 2 …
    # h2 タグで分割して各ブロックをパース
    blocks = re.split(r'<h2[^>]*>', html, flags=re.IGNORECASE)
    results = []
    for block in blocks[1:]:  # 最初のブロックはヘッダ前なのでスキップ
        p = _HwPageParser()
        p.feed(block)
        p.close()
        flat = p.flat()
        if flat:
            results.append(flat)
    return results


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
        # port 指定あり → そのまま使う
        # port 未指定 → HTTP:16992 をデフォルトとして即座に使用（probe しない）
        # HTTPS:16993 が必要なら port=16993 を明示してください
        if port:
            scheme = "https" if port == AMT_DEFAULT_PORT else "http"
            resolved_port = port
        else:
            scheme, resolved_port = "http", AMT_HTTP_PORT
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
            items = []
        ns = f"{_CIM}CIM_Chassis"
        for item in items:
            return SystemInfo(
                manufacturer=_xml_text(item, "Manufacturer", ns),
                model=_xml_text(item, "Model", ns),
                serial=_xml_text(item, "SerialNumber", ns),
            )
        # フォールバック: hw-sys.htm (Platform セクション)
        html = self._fetch_hw_page("hw-sys.htm")
        if html:
            sections = _parse_amt_hw_page(html)
            if sections:
                p = sections[0]
                return SystemInfo(
                    manufacturer=p.get("Manufacturer", "").strip(),
                    model=p.get("Computer model", "").strip(),
                    serial=p.get("Serial number", "").strip(),
                )
        return SystemInfo()

    def _collect_processors(self) -> list[Component]:
        out = []
        try:
            items = self._enumerate("CIM_Processor")
        except BMCError:
            items = []
        ns = f"{_CIM}CIM_Processor"
        for item in items:
            name = _xml_text(item, "DeviceID", ns) or _xml_text(item, "Name", ns) or "CPU"
            cores = _xml_text(item, "NumberOfCores", ns)
            threads = _xml_text(item, "NumberOfLogicalProcessors", ns)
            mfr = _xml_text(item, "Manufacturer", ns)
            model = _xml_text(item, "Name", ns)
            # ベースクロックはモデル名の "@ X.XXGHz" から取る (MaxClockSpeed はブーストクロック)
            speed_mhz = _base_clock_mhz_from_model(model)
            desc_parts = []
            if cores:
                desc_parts.append(f"{cores}C")
            if threads:
                desc_parts[-1] += f"/{threads}T" if desc_parts else f"{threads}T"
            if speed_mhz:
                desc_parts.append(_fmt_ghz(speed_mhz))
            out.append(Component(
                kind="cpu",
                name=name,
                manufacturer=mfr,
                part_id=model,
                description=" ".join(desc_parts),
                extra={
                    "cores": int(cores) if cores else 0,
                    "speed_mhz": speed_mhz,
                },
                source_path=self._endpoint,
            ))
        # HTML補完: part_id または manufacturer が空なら hw-proc.htm で埋める
        if out and not all(c.part_id and c.manufacturer for c in out):
            html_procs = _parse_amt_hw_page(self._fetch_hw_page("hw-proc.htm"))
            for i, comp in enumerate(out):
                if i < len(html_procs):
                    p = html_procs[i]
                    if not comp.part_id:
                        comp.part_id = p.get("Version", "").strip()
                    if not comp.manufacturer:
                        comp.manufacturer = p.get("Manufacturer", "").strip()
                    # part_id が補完されたらベースクロックも更新
                    if not comp.extra.get("speed_mhz") and comp.part_id:
                        base = _base_clock_mhz_from_model(comp.part_id)
                        if base:
                            comp.extra["speed_mhz"] = base
                            # description の末尾にクロックを追加
                            comp.description = (comp.description + " " + _fmt_ghz(base)).strip()
        if out:
            return out
        # フォールバック: hw-proc.htm
        html = self._fetch_hw_page("hw-proc.htm")
        if not html:
            return []
        for idx, proc in enumerate(_parse_amt_hw_page(html)):
            model_name = proc.get("Version", "").strip()
            mfr = proc.get("Manufacturer", "").strip()
            speed_mhz = _base_clock_mhz_from_model(model_name)
            desc = _fmt_ghz(speed_mhz) if speed_mhz else ""
            out.append(Component(
                kind="cpu",
                name=f"CPU {idx}",
                manufacturer=mfr,
                part_id=model_name,
                description=desc,
                extra={"speed_mhz": speed_mhz},
                source_path=self._endpoint,
            ))
        return out

    def _collect_memory(self) -> list[Component]:
        out = []
        try:
            items = self._enumerate("CIM_PhysicalMemory")
        except BMCError:
            items = []
        ns = f"{_CIM}CIM_PhysicalMemory"
        for item in items:
            # Tag が数字のみ (Asset Tag) の場合は DeviceLocator を優先
            _tag = _xml_text(item, "Tag", ns)
            _locator = _xml_text(item, "DeviceLocator", ns)
            tag = (_locator or _tag) if (not _tag or _tag.strip().replace(" ", "").isdigit()) else _tag
            tag = tag or "DIMM"
            cap_bytes = _xml_text(item, "Capacity", ns)
            # Speed=0 の場合は ConfiguredMemoryClockSpeed / MaxMemorySpeed を使う
            _speed_raw = _xml_text(item, "Speed", ns)
            speed = (_speed_raw if _speed_raw and _speed_raw != "0" else None) or (
                _xml_text(item, "ConfiguredMemoryClockSpeed", ns)
                or _xml_text(item, "MaxMemorySpeed", ns)
            )
            part = _xml_text(item, "PartNumber", ns)
            serial = _xml_text(item, "SerialNumber", ns)
            _mfr = _xml_text(item, "Manufacturer", ns)
            # JEDEC コード (16 進数のみの長い文字列) は除外
            mfr = "" if (_mfr and re.fullmatch(r'[0-9A-Fa-f]+', _mfr)) else _mfr
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
        if out:
            return out
        # フォールバック: hw-mem.htm
        html = self._fetch_hw_page("hw-mem.htm")
        if not html:
            return []
        for idx, mod in enumerate(_parse_amt_hw_page(html)):
            size_str = mod.get("Size", "")
            speed_str = mod.get("Speed", "")
            size_mb = 0
            if size_str:
                try:
                    size_mb = int(size_str.split()[0])
                except (ValueError, IndexError):
                    pass
            size_gb = size_mb // 1024 if size_mb else 0
            speed_mhz = speed_str.split()[0] if speed_str else ""
            desc = f"{size_gb}GB" if size_gb else ""
            if speed_mhz:
                desc += f" {speed_mhz}MHz"
            out.append(Component(
                kind="memory",
                name=f"Module {idx + 1}",
                manufacturer=mod.get("Manufacturer", "").strip(),
                part_id=mod.get("Part number", "").strip(),
                serial=mod.get("Serial number", "").strip(),
                description=desc.strip(),
                extra={"capacity_mib": size_gb * 1024 if size_gb else 0},
                source_path=self._endpoint,
            ))
        return out

    def _fetch_hw_page(self, page: str) -> str:
        """AMT web UI の hw-*.htm を取得して HTML を返す。失敗時は空文字。"""
        base = self._endpoint.replace("/wsman", "")
        try:
            with self._suppress_ssl_warnings():
                r = self._session.get(f"{base}/{page}", timeout=self.timeout)
            return r.text if r.status_code == 200 else ""
        except requests.RequestException:
            return ""

    def _collect_drives(self) -> list[Component]:
        # hw-disk.htm から Model / Serial / Size を取得（WS-MAN では取得不可）
        html = self._fetch_hw_page("hw-disk.htm")
        if html:
            return self._parse_drives_from_html(html)
        # フォールバック: CIM_MediaAccessDevice からサイズのみ
        return self._collect_drives_cim()

    def _parse_drives_from_html(self, html: str) -> list[Component]:
        out = []
        for idx, disk in enumerate(_parse_amt_hw_page(html)):
            model = disk.get("Model", "").strip()
            serial = disk.get("Serial number", "").strip()
            size_str = disk.get("Size", "")
            size_mb = 0
            if size_str:
                try:
                    size_mb = int(size_str.split()[0])
                except (ValueError, IndexError):
                    pass
            size_gb = size_mb // 1024 if size_mb else 0
            desc = f"{size_gb}GB" if size_gb else ""
            vendor = model.split()[0] if model else ""
            out.append(Component(
                kind="drive",
                name=model or f"MEDIA DEV {idx}",
                serial=serial,
                description=desc,
                part_id=model,
                manufacturer=vendor,
                extra={"size_gb": size_gb},
                source_path=self._endpoint,
            ))
        return out

    def _collect_drives_cim(self) -> list[Component]:
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
