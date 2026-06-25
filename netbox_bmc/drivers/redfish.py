"""
Redfish ドライバ。

マルチベンダー対応の要点:
1. URI をハードコードしない。/redfish/v1 (ServiceRoot) から
   Systems → Members → Processors/Memory/Storage... とリンクを辿る。
   これで iDRAC (System.Embedded.1) も iLO (/Systems/1) も同じコードで動く。
2. ServiceRoot の Vendor / Oem キーからベンダーを判別し、
   OEM 拡張が必要な場合のみサブクラスをディスパッチする。
3. セッション認証 (X-Auth-Token) を優先し、失敗時は Basic 認証へフォールバック。
"""
from __future__ import annotations

import logging

import requests
import urllib3

from ..inventory import Component, InventoryResult, SystemInfo
from .base import BaseDriver, BMCError

logger = logging.getLogger("netbox_bmc.redfish")

POWER_ACTION_MAP = {
    "on": "On",
    "off": "ForceOff",
    "soft": "GracefulShutdown",
    "cycle": "PowerCycle",
    "reset": "ForceRestart",
}


def probe_redfish(address: str, timeout: int = 5, verify_ssl: bool = False) -> bool:
    """Redfish サービスの存在確認。

    `/redfish/v1` は Redfish 仕様で固定の ServiceRoot URI なので直書き許容。
    配下のリソース URI は ServiceRoot のリンクを辿って解決する。
    """
    import warnings
    try:
        with warnings.catch_warnings():
            if not verify_ssl:
                warnings.simplefilter(
                    "ignore", urllib3.exceptions.InsecureRequestWarning,
                )
            r = requests.get(f"https://{address}/redfish/v1",
                             timeout=timeout, verify=verify_ssl)
        return r.status_code == 200 and "redfish" in r.text.lower()
    except requests.RequestException:
        return False


def _clean(s) -> str:
    """Strip whitespace and stray backslashes from Redfish string fields."""
    return (s or "").strip().strip("\\").strip()


def _infer_cpu_arch(arch_field: str | None, manufacturer: str) -> str:
    if arch_field:
        return arch_field
    mfr = manufacturer.lower()
    if "intel" in mfr or "advanced micro" in mfr or "amd" in mfr:
        return "x86-64"
    if "arm" in mfr:
        return "ARM"
    return ""


def _iter_odata_ids(obj, _seen=None) -> list[str]:
    """JSON 値から @odata.id 文字列を再帰的に収集する。"""
    if _seen is None:
        _seen = set()
    result = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "@odata.id" and isinstance(v, str) and v not in _seen:
                _seen.add(v)
                result.append(v)
            else:
                result.extend(_iter_odata_ids(v, _seen))
    elif isinstance(obj, list):
        for item in obj:
            result.extend(_iter_odata_ids(item, _seen))
    return result


class RedfishDriver(BaseDriver):
    protocol = "redfish"
    vendor = "Generic"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base = f"https://{self.address}"
        if self.port:
            self.base = f"https://{self.address}:{self.port}"
        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        self._session_uri = None
        self._login()

    # --- HTTP ヘルパ ------------------------------------------------------
    def _suppress_ssl_warnings(self):
        """verify_ssl=False の HTTP 呼び出しに付ける warnings filter。

        urllib3.disable_warnings はプロセス全体に副作用を残すので、
        本ドライバの HTTP I/O スコープに限定する。
        """
        import warnings
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            with warnings.catch_warnings():
                if not self.verify_ssl:
                    warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
                yield

        return _cm()

    def _url(self, path: str) -> str:
        """相対パス (/...) は self.base に連結し、絶対URL はそのまま返す。"""
        return path if path.startswith("http") else f"{self.base}{path}"

    def _login(self):
        """セッション認証を試み、失敗したら Basic 認証へ。"""
        try:
            with self._suppress_ssl_warnings():
                r = self.session.post(
                    f"{self.base}/redfish/v1/SessionService/Sessions",
                    json={"UserName": self.username, "Password": self.password},
                    timeout=self.timeout,
                )
            if r.status_code in (200, 201):
                self.session.headers["X-Auth-Token"] = r.headers["X-Auth-Token"]
                self._session_uri = r.headers.get("Location")
                return
            logger.debug(
                "Session auth on %s returned HTTP %s, falling back to Basic: %s",
                self.address, r.status_code, r.text[:200],
            )
        except requests.RequestException as e:
            logger.debug("Session auth on %s failed (%s), falling back to Basic",
                         self.address, e)
        self.session.auth = (self.username, self.password)

    def _get(self, path: str) -> dict:
        url = self._url(path)
        try:
            with self._suppress_ssl_warnings():
                r = self.session.get(url, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            raise BMCError(f"Redfish GET {path} failed: {e}") from e

    def _get_optional(self, path: str) -> dict | None:
        """403/404 など取得不可のリソースは None を返し、呼び出し元でスキップさせる。"""
        try:
            return self._get(path)
        except BMCError as e:
            logger.warning("Skipping inaccessible resource %s: %s", path, e)
            return None

    def _collection(self, resource: dict, key: str) -> list[dict]:
        """resource[key]["@odata.id"] のコレクションを展開して各 Member を返す。

        各 Member dict に "@odata.id" が含まれるため呼び出し元で source_path として使える。
        一部の実装では resource[key] がリスト形式で直接 @odata.id 参照を返す場合があり、
        その場合も正しく展開する。
        """
        val = resource.get(key, {})
        if isinstance(val, list):
            members = []
            for m in val:
                if isinstance(m, dict) and m.get("@odata.id"):
                    item = self._get_optional(m["@odata.id"])
                    if item is not None:
                        members.append(item)
            return members
        ref = val.get("@odata.id")
        if not ref:
            return []
        coll = self._get_optional(ref)
        if coll is None:
            return []
        members = []
        for m in coll.get("Members", []):
            item = self._get_optional(m["@odata.id"])
            if item is not None:
                members.append(item)
        return members

    def fetch_raw(self, max_depth: int = 2) -> dict:
        """デバッグ用: ServiceRoot から max_depth 階層を再帰取得して返す。

        Returns:
            {"ok": {path: data}, "errors": {path: error_message}}
        """
        ok: dict = {}
        errors: dict = {}

        def _fetch(path: str, depth: int) -> None:
            if path in ok or path in errors:
                return
            try:
                data = self._get(path)
                ok[path] = data
            except BMCError as e:
                errors[path] = str(e)
                return
            if depth >= max_depth:
                return
            for val in _iter_odata_ids(data):
                _fetch(val, depth + 1)

        _fetch("/redfish/v1", 0)
        return {"ok": ok, "errors": errors}

    # --- インベントリ -----------------------------------------------------
    def get_inventory(self) -> InventoryResult:
        root = self._get("/redfish/v1")
        systems = self._collection(root, "Systems")
        if not systems:
            raise BMCError("No ComputerSystem found")
        sysres = systems[0]  # マルチノードシャーシは将来拡張

        system = SystemInfo(
            manufacturer=(sysres.get("Manufacturer") or "").strip(),
            model=(sysres.get("Model") or "").strip(),
            serial=(sysres.get("SerialNumber") or "").strip(),
            sku=(sysres.get("SKU") or "").strip(),
            uuid=(sysres.get("UUID") or "").strip(),
            bios_version=(sysres.get("BiosVersion") or "").strip(),
            power_state=sysres.get("PowerState", ""),
            hostname=sysres.get("HostName") or "",
        )

        components: list[Component] = []
        components += self._collect_processors(sysres)
        components += self._collect_memory(sysres)
        components += self._collect_drives(sysres)
        components += self._collect_nics(sysres)
        components += self._collect_psu(sysres)
        components += self._collect_fans(sysres)
        components += self._collect_pcie_devices(sysres)
        components += self._collect_firmware(root)

        return InventoryResult(
            system=system,
            components=components,
            vendor=self.detect_vendor(root, sysres),
            protocol=self.protocol,
        )

    def _collect_processors(self, sysres) -> list[Component]:
        out = []
        for p in self._collection(sysres, "Processors"):
            if p.get("Status", {}).get("State") == "Absent":
                continue
            out.append(Component(
                kind="cpu",
                name=p.get("Id") or p.get("Socket") or "CPU",
                manufacturer=_clean(p.get("Manufacturer")),
                part_id=_clean(p.get("Model") or p.get("Version")),
                extra={
                    "cores": p.get("TotalCores") or 0,
                    "speed_mhz": p.get("OperatingSpeedMHz") or 0,
                    "architecture": _infer_cpu_arch(
                        p.get("ProcessorArchitecture"),
                        p.get("Manufacturer", ""),
                    ),
                },
                description=(
                    f"{p.get('TotalCores', '?')}C/{p.get('TotalThreads', '?')}T"
                    + (f" @ {p['OperatingSpeedMHz']}MHz" if p.get("OperatingSpeedMHz") else "")
                ),
                source_path=p.get("@odata.id", ""),
            ))
        return out

    def _collect_memory(self, sysres) -> list[Component]:
        out = []
        for m in self._collection(sysres, "Memory"):
            if m.get("Status", {}).get("State") == "Absent":
                continue
            size = m.get("CapacityMiB")
            size_str = f"{size // 1024}GB" if size else "?"
            out.append(Component(
                kind="memory",
                name=m.get("DeviceLocator") or m.get("Id") or "DIMM",
                manufacturer=m.get("Manufacturer", "").strip(),
                part_id=(m.get("PartNumber") or "").strip(),
                serial=(m.get("SerialNumber") or "").strip(),
                description=f"{size_str} {m.get('MemoryDeviceType', '')} "
                            f"{m.get('OperatingSpeedMhz', '')}MHz".strip(),
                extra={
                    "capacity_mib": size or 0,
                    "memory_device_type": m.get("MemoryDeviceType", ""),
                    "operating_speed_mhz": (
                        max(m["AllowedSpeedsMHz"])
                        if m.get("AllowedSpeedsMHz")
                        else m.get("OperatingSpeedMhz") or 0
                    ),
                    "ecc": "ECC" in (m.get("ErrorCorrection") or ""),
                },
                source_path=m.get("@odata.id", ""),
            ))
        return out

    def _collect_drives(self, sysres) -> list[Component]:
        out = []
        for storage in self._collection(sysres, "Storage"):
            for dref in storage.get("Drives", []):
                d = self._get_optional(dref["@odata.id"])
                if d is None:
                    continue
                if d.get("Status", {}).get("State") == "Absent":
                    continue
                cap = d.get("CapacityBytes")
                cap_str = f"{cap / 1e12:.1f}TB" if cap and cap >= 1e12 else (
                    f"{cap / 1e9:.0f}GB" if cap else "?")
                mfr = (d.get("Manufacturer") or "").strip()
                model = (d.get("Model") or "").strip()
                if not mfr and model:
                    parts = model.split(None, 1)
                    if len(parts) == 2 and parts[0].isalpha() and parts[0].isupper():
                        mfr, model = parts[0], parts[1]
                out.append(Component(
                    kind="drive",
                    name=d.get("Id") or d.get("Name") or "Drive",
                    manufacturer=mfr,
                    part_id=model,
                    serial=(d.get("SerialNumber") or "").strip(),
                    firmware=(d.get("Revision") or "").strip(),
                    description=f"{cap_str} {d.get('MediaType', '')} "
                                f"{d.get('Protocol', '')}".strip(),
                    extra={"capacity_bytes": cap or 0},
                    source_path=dref["@odata.id"],
                ))
        return out

    def _collect_nics(self, sysres) -> list[Component]:
        out = []
        for nic in self._collection(sysres, "EthernetInterfaces"):
            if nic.get("Status", {}).get("State") == "Absent":
                continue
            mac = nic.get("MACAddress") or nic.get("PermanentMACAddress") or ""
            out.append(Component(
                kind="nic",
                name=nic.get("Id") or "NIC",
                description=nic.get("Description", ""),
                extra={"mac": mac.upper(), "speed_mbps": nic.get("SpeedMbps")},
                source_path=nic.get("@odata.id", ""),
            ))
        return out

    def _collect_psu(self, sysres) -> list[Component]:
        """Collect Power Supply Unit components from Chassis.Power resource."""
        out = []
        for chassis_ref in sysres.get("Links", {}).get("Chassis", [])[:1]:
            chassis = self._get_optional(chassis_ref.get("@odata.id", ""))
            if not chassis:
                continue
            power_ref = chassis.get("Power", {}).get("@odata.id")
            if not power_ref:
                continue
            power = self._get_optional(power_ref)
            if not power:
                continue
            for psu in power.get("PowerSupplies", []):
                if psu.get("Status", {}).get("State") == "Absent":
                    continue
                out.append(Component(
                    kind="psu",
                    name=psu.get("MemberId") or psu.get("Name", "PSU"),
                    manufacturer=_clean(psu.get("Manufacturer")),
                    part_id=_clean(psu.get("PartNumber") or psu.get("Model")),
                    serial=_clean(psu.get("SerialNumber")),
                    description=_clean(psu.get("Name")),
                    firmware=_clean(psu.get("FirmwareVersion")),
                    source_path=power_ref,
                ))
        return out

    def _collect_fans(self, sysres) -> list[Component]:
        """Collect Fan components from Chassis.Thermal resource."""
        out = []
        for chassis_ref in sysres.get("Links", {}).get("Chassis", [])[:1]:
            chassis = self._get_optional(chassis_ref.get("@odata.id", ""))
            if not chassis:
                continue
            thermal_ref = chassis.get("Thermal", {}).get("@odata.id")
            if not thermal_ref:
                continue
            thermal = self._get_optional(thermal_ref)
            if not thermal:
                continue
            for fan in thermal.get("Fans", []):
                if fan.get("Status", {}).get("State") == "Absent":
                    continue
                out.append(Component(
                    kind="fan",
                    name=fan.get("MemberId") or fan.get("FanName") or fan.get("Name", "Fan"),
                    manufacturer=(fan.get("Manufacturer") or "").strip(),
                    description=(fan.get("FanName") or fan.get("Name") or "").strip(),
                    source_path=thermal_ref,
                ))
        return out

    def _collect_pcie_devices(self, sysres) -> list[Component]:
        """Collect PCIe device components from System.PCIeDevices resource."""
        out = []
        for pcie in self._collection(sysres, "PCIeDevices"):
            if pcie.get("Status", {}).get("State") == "Absent":
                continue
            out.append(Component(
                kind="pci",
                name=pcie.get("Id") or pcie.get("Name", "PCIe"),
                manufacturer=(pcie.get("Manufacturer") or "").strip(),
                part_id=(pcie.get("Model") or "").strip(),
                serial=(pcie.get("SerialNumber") or "").strip(),
                description=(pcie.get("Name") or "").strip(),
                source_path=pcie.get("@odata.id", ""),
            ))
        return out

    def _collect_firmware(self, root) -> list[Component]:
        """UpdateService/FirmwareInventory からファームウェア一覧を取得。"""
        out = []
        try:
            us_ref = root.get("UpdateService", {}).get("@odata.id")
            if not us_ref:
                return out
            us = self._get(us_ref)
            for fw in self._collection(us, "FirmwareInventory"):
                if not fw.get("Version"):
                    continue
                out.append(Component(
                    kind="firmware",
                    name=fw.get("Id") or fw.get("Name", "Firmware"),
                    description=fw.get("Name", ""),
                    firmware=fw.get("Version", ""),
                    source_path=fw.get("@odata.id", ""),
                ))
        except BMCError:
            logger.debug("FirmwareInventory not available on %s", self.address)
        return out

    # --- 電源操作 ----------------------------------------------------------
    def get_power_state(self) -> str:
        root = self._get("/redfish/v1")
        systems = self._collection(root, "Systems")
        return systems[0].get("PowerState", "Unknown") if systems else "Unknown"

    def set_power(self, action: str) -> None:
        reset_type = POWER_ACTION_MAP.get(action)
        if not reset_type:
            raise BMCError(f"Unknown power action: {action}")
        root = self._get("/redfish/v1")
        systems = self._collection(root, "Systems")
        target = (systems[0].get("Actions", {})
                  .get("#ComputerSystem.Reset", {}).get("target"))
        if not target:
            raise BMCError("ComputerSystem.Reset action not found")
        with self._suppress_ssl_warnings():
            r = self.session.post(
                self._url(target),
                json={"ResetType": reset_type},
                timeout=self.timeout,
            )
        if r.status_code not in (200, 202, 204):
            raise BMCError(f"Power action failed: HTTP {r.status_code} {r.text[:200]}")

    # --- ベンダー検出 -------------------------------------------------------
    @staticmethod
    def detect_vendor(root: dict, sysres: dict | None = None) -> str:
        vendor = root.get("Vendor", "")
        if vendor:
            return vendor
        oem_keys = set(root.get("Oem", {}).keys())
        if sysres:
            oem_keys |= set(sysres.get("Oem", {}).keys())
        for key, name in (("Dell", "Dell"), ("Hpe", "HPE"), ("Hp", "HPE"),
                          ("Lenovo", "Lenovo"), ("Supermicro", "Supermicro")):
            if key in oem_keys:
                return name
        if sysres and sysres.get("Manufacturer"):
            return sysres["Manufacturer"]
        return "Generic"

    def close(self):
        if self._session_uri:
            try:
                with self._suppress_ssl_warnings():
                    self.session.delete(self._url(self._session_uri), timeout=5)
            except requests.RequestException:
                pass
        self.session.close()


# --- ベンダーサブクラス (OEM 拡張が必要な場合のみオーバーライド) ----------

class DellRedfishDriver(RedfishDriver):
    """iDRAC: Oem.Dell 配下にジョブキューや詳細 FRU 情報がある。"""
    vendor = "Dell"


class HPERedfishDriver(RedfishDriver):
    """iLO: 古い iLO4 は Redfish 準拠度が低いので必要に応じて補正。"""
    vendor = "HPE"


class LenovoRedfishDriver(RedfishDriver):
    """XCC。"""
    vendor = "Lenovo"


VENDOR_DRIVERS = {
    "Dell": DellRedfishDriver,
    "HPE": HPERedfishDriver,
    "Lenovo": LenovoRedfishDriver,
}


def build_redfish_driver(address, username, password, **kwargs) -> RedfishDriver:
    """汎用ドライバで接続→ベンダー検出→必要ならサブクラスへ差し替え。

    ServiceRoot 取得失敗 (BMCError) は呼び出し元へ伝播させる
    (接続失敗を隠蔽しない)。ベンダー判定が "Generic" に落ちるだけのケースは
    Generic ドライバで続行できるよう、検出ロジックの結果が空でも例外にしない。
    """
    driver = RedfishDriver(address, username, password, **kwargs)
    try:
        root = driver._get("/redfish/v1")
    except BMCError:
        driver.close()
        raise
    vendor = RedfishDriver.detect_vendor(root)
    cls = VENDOR_DRIVERS.get(vendor)
    if cls and cls is not type(driver):
        driver.close()
        return cls(address, username, password, **kwargs)
    return driver
