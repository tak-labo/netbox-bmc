"""
IPMI ドライバ (レガシー BMC 向けフォールバック)。

pyghmi の get_inventory() で FRU 情報を取得する。
Redfish より取得できる情報は限定的 (CPU/DIMM の詳細は出ないことが多い)。
既存 netbox-ipmi-plugin の電源操作・SOL 周りはここに段階的に移植する。
"""
from __future__ import annotations

import ipaddress
import logging
import re as _re

from ..inventory import (
    BmcNetworkInterface,
    Component,
    InventoryResult,
    ManagerInfo,
    SelEntry,
    SensorReading,
    SystemInfo,
)
from .base import BaseDriver, BMCError

logger = logging.getLogger("netbox_bmc.ipmi")

# IPMI Chassis Control command (netfn=0x00, cmd=0x02) data byte values
# Bypasses pyghmi OEM/SDR init that triggers sorting bugs on some BMC firmware
_CHASSIS_CTRL = {
    "on":    0x01,  # Power Up
    "off":   0x00,  # Power Down
    "cycle": 0x02,  # Power Cycle
    "reset": 0x03,  # Hard Reset
    "soft":  0x05,  # Soft-off via ACPI
}

# SDR センサー type -> SensorReading.kind
_SENSOR_KIND_MAP = {
    "Temperature": "temperature",
    "Fan": "fan",
    "Voltage": "voltage",
    "Power Supply": "power",
    "Power Unit": "power",
    "Current": "power",
}


def _health_str(health_bits: int) -> str:
    """pyghmi の const.Health ビットマスクを人間向け文字列に変換する。"""
    if health_bits & 4:
        return "Failed"
    if health_bits & 2:
        return "Critical"
    if health_bits & 1:
        return "Warning"
    return "OK"


def _make_safe_command_class(command_module):
    """Return a Command subclass that tolerates SDR/OEM init failures.

    pyghmi calls oem_init() inside raw_command(), so even raw chassis commands
    hit the SDR sort bug ('float' vs 'NoneType') on some BMC firmware.
    Swallowing the error and marking initialized lets raw_command proceed.
    """
    class _SafeCommand(command_module.Command):
        def oem_init(self):
            if getattr(self, "oem_initialized", False):
                return
            try:
                super().oem_init()
            except Exception as e:
                logger.warning("IPMI OEM/SDR init failed (suppressed): %s", e)
            finally:
                self.oem_initialized = True

    return _SafeCommand


def _purge_stale_pyghmi_session(bmc: str, userid: str, password: str, port: int) -> None:
    """pyghmi の process-wide セッションキャッシュから該当エントリを強制的に破棄する。

    pyghmi.ipmi.private.session.Session は (bmc, userid, password, port, kg) をキーに
    Session インスタンスをプロセス全体で使い回す設計になっている
    (Session.__new__ の bmc_handlers / initting_sessions)。このプラグインは HTTP
    リクエストごとに新しい IPMIDriver を都度生成・破棄する設計のため、この使い回しは
    都合が悪い: __init__ の早期 return パス (`hasattr(self, "initialized")`) では
    logoutexpiry がリセットされないまま __new__ 側で強制的に logging=True が
    セットされることがあり、その状態で raw_command() のポーリングループ
    (`_monotonic_time() < self.logoutexpiry`) が None と比較されて
    `TypeError: '<' not supported between instances of 'float' and 'NoneType'` になる
    (pyghmi 側のバグ)。呼び出しごとに毎回キャッシュを破棄し、必ず新規 Session を
    作らせることで回避する。
    """
    try:
        from pyghmi.ipmi.private import session as pysession
    except ImportError:
        return
    pysession.Session.initting_sessions.pop((bmc, userid, password, port, None), None)
    for sockaddr, ports in list(pysession.Session.bmc_handlers.items()):
        for sess_port, sess in list(ports.items()):
            if sess.bmc == bmc:
                del pysession.Session.bmc_handlers[sockaddr][sess_port]


class IPMIDriver(BaseDriver):
    protocol = "ipmi"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            from pyghmi.ipmi import command
        except ImportError as e:
            raise BMCError("pyghmi is not installed") from e
        port = self.port or 623
        _purge_stale_pyghmi_session(self.address, self.username, self.password, port)
        try:
            SafeCommand = _make_safe_command_class(command)
            self.cmd = SafeCommand(
                bmc=self.address,
                userid=self.username,
                password=self.password,
                port=port,
            )
        except Exception as e:
            raise BMCError(f"IPMI connection to {self.address} failed: {e}") from e

    def get_inventory(self) -> InventoryResult:
        system = SystemInfo()
        components: list[Component] = []
        gen = self.cmd.get_inventory()
        while True:
            try:
                name, info = next(gen)
            except StopIteration:
                break
            except Exception as e:
                # SDR 読み込みエラー (NotImplementedError / TypeError 等) は
                # FRU 0 (System) 取得後に発生することが多い。取得済みデータで続行。
                logger.warning("IPMI inventory partial failure: %s", e)
                break
            if info is None:
                continue
            if name == "System":
                system.manufacturer = (info.get("Manufacturer")
                                       or info.get("Board manufacturer") or "")
                system.model = next(
                    (v for v in (
                        info.get("Product name"),
                        info.get("Model"),
                        info.get("Board product name"),
                    ) if v and v.upper() != "NONE"),
                    "",
                )
                system.serial = (info.get("Serial Number")
                                 or info.get("Board serial number") or "")
                system.uuid = str(info.get("UUID") or "")
            elif name == "BMC FRU":
                # duplicate of System FRU — skip
                pass
            else:
                components.append(Component(
                    kind=_guess_kind(name),
                    name=name,
                    manufacturer=info.get("Manufacturer", "") or "",
                    part_id=info.get("Part Number", "")
                            or info.get("Product name", "") or "",
                    serial=info.get("Serial Number", "") or "",
                ))

        components.extend(_components_from_sensors(self.cmd))

        return InventoryResult(system=system, components=components,
                               vendor=system.manufacturer or "Unknown",
                               protocol=self.protocol)

    def get_power_state(self) -> str:
        # netfn=0x00 cmd=0x01 = Get Chassis Status; avoids OEM/SDR init
        try:
            resp = self.cmd.raw_command(netfn=0, command=1)
            if "error" in resp:
                raise BMCError(resp["error"])
            return "on" if (resp["data"][0] & 1) else "off"
        except BMCError:
            raise
        except Exception as e:
            raise BMCError(str(e)) from e

    def set_power(self, action: str) -> None:
        ctrl = _CHASSIS_CTRL.get(action)
        if ctrl is None:
            raise BMCError(f"Unknown power action: {action}")
        try:
            resp = self.cmd.raw_command(netfn=0, command=2, data=[ctrl])
            if "error" in resp:
                raise BMCError(f"IPMI power action failed: {resp['error']}")
        except BMCError:
            raise
        except Exception as e:
            raise BMCError(f"IPMI power action failed: {e}") from e

    def get_network_config(self) -> list[BmcNetworkInterface]:
        """"Get LAN Configuration Parameters" (netfn=0x0c cmd=0x02) 経由で取得。

        IPMI の LAN チャンネルは通常1系統のみ管理対象となるため要素数1の
        リストを返す (Redfish 側は複数インターフェースを返せるため list に統一)。
        DNS サーバはこの IPMI LAN パラメータには含まれないため空のまま。
        hostname / IPv6 は OEM・実装依存 (未対応 BMC では例外/空) のため
        いずれもベストエフォート。
        """
        try:
            channel = self.cmd.get_network_channel()
            cfg = self.cmd.get_net_configuration(channel)
        except Exception as e:
            raise BMCError(f"IPMI network configuration failed: {e}") from e

        ipv4_address = ""
        ipv4_subnet_mask = ""
        addr_cidr = cfg.get("ipv4_address")
        if addr_cidr:
            try:
                iface = ipaddress.ip_interface(addr_cidr)
                ipv4_address = str(iface.ip)
                ipv4_subnet_mask = str(iface.netmask)
            except ValueError:
                ipv4_address = addr_cidr

        hostname = ""
        try:
            hostname = self.cmd.get_hostname() or ""
        except Exception as e:
            logger.debug("IPMI get_hostname failed (suppressed): %s", e)

        ipv6_addresses: list[str] = []
        ipv6_gateway = ""
        try:
            cfg6 = self.cmd.get_net6_configuration(channel)
            ipv6_addresses = cfg6.get("static_addrs") or []
            ipv6_gateway = cfg6.get("static_gateway") or ""
        except Exception as e:
            logger.debug("IPMI get_net6_configuration failed (suppressed): %s", e)

        cfg_method = cfg.get("ipv4_configuration")
        return [BmcNetworkInterface(
            name=f"channel{channel}",
            dhcp_enabled=(cfg_method == "DHCP") if cfg_method else None,
            ipv4_address=ipv4_address,
            ipv4_subnet_mask=ipv4_subnet_mask,
            ipv4_gateway=cfg.get("ipv4_gateway") or "",
            ipv6_addresses=ipv6_addresses,
            ipv6_gateway=ipv6_gateway,
            mac_address=(cfg.get("mac_address") or "").upper(),
            hostname=hostname,
            vlan_id=cfg.get("vlan_id") or None,
        )]

    def get_manager_info(self) -> ManagerInfo:
        """"Get Device ID" (netfn=0x06 cmd=0x01, 標準IPMI・OEM非依存) でファームウェア
        バージョンを取得し、pyghmi の get_health() でヘルスを取得する。
        """
        try:
            resp = self.cmd.raw_command(netfn=0x06, command=0x01)
            if "error" in resp:
                raise BMCError(resp["error"])
            data = resp["data"]
            major = data[2] & 0b1111111
            minor_hi = (data[3] >> 4) & 0b1111
            minor_lo = data[3] & 0b1111
            firmware_version = f"{major}.{minor_hi}{minor_lo}"
        except BMCError:
            raise
        except Exception as e:
            raise BMCError(f"IPMI Get Device ID failed: {e}") from e

        health = ""
        try:
            summary = self.cmd.get_health()
            health_bits = summary.get("health", 0)
            if health_bits & 4:
                health = "Failed"
            elif health_bits & 2:
                health = "Critical"
            elif health_bits & 1:
                health = "Warning"
            else:
                health = "OK"
        except Exception as e:
            logger.debug("IPMI get_health failed (suppressed): %s", e)

        return ManagerInfo(firmware_version=firmware_version, health=health)

    def set_identify(self, on: bool) -> None:
        """標準の "Chassis Identify" コマンド (netfn=0x00 cmd=0x04) を利用する。

        pyghmi の set_identify() は既にこの raw コマンドを正しく組み立てる
        実装を持つため、バイト処理を自前で再実装せずそのまま呼び出す。
        """
        try:
            self.cmd.set_identify(on=on)
        except Exception as e:
            raise BMCError(f"IPMI identify action failed: {e}") from e

    def get_sensors(self) -> list[SensorReading]:
        """get_sensor_data() (既に _components_from_sensors で呼んでいる) の
        各読み取りから数値 (温度/Fan回転数/電圧/消費電力) を保持して返す。
        """
        try:
            sensors = list(self.cmd.get_sensor_data())
        except Exception as e:
            raise BMCError(f"IPMI get_sensor_data failed: {e}") from e

        readings: list[SensorReading] = []
        for s in sensors:
            stype = getattr(s, "type", "") or ""
            kind = _SENSOR_KIND_MAP.get(stype)
            if kind is None:
                continue
            readings.append(SensorReading(
                name=getattr(s, "name", "") or "",
                kind=kind,
                value=getattr(s, "value", None),
                units=getattr(s, "units", "") or "",
                status=_health_str(getattr(s, "health", 0)),
            ))
        return readings

    def get_event_log(self, limit: int = 20) -> list[SelEntry]:
        """pyghmi の get_event_log() (SDR経由でSELを取得) で直近 limit 件を返す。

        SDR依存のため _components_from_sensors と同様に脆い可能性がある
        (一部BMCファームウェアでNotImplementedError/TypeError等が出ることがある)。
        """
        try:
            records = list(self.cmd.get_event_log())
        except Exception as e:
            raise BMCError(f"IPMI get_event_log failed: {e}") from e

        records = records[-limit:]
        records.reverse()  # 新しい順

        return [
            SelEntry(
                created=r.get("timestamp", "") or "",
                severity=_health_str(r.get("severity", 0)),
                message=r.get("event", "") or "",
                sensor_type=r.get("component", "") or "",
            )
            for r in records
        ]

    def close(self):
        try:
            self.cmd.ipmi_session.logout()
        except Exception:
            pass


def _components_from_sensors(cmd) -> list[Component]:
    """SDR センサー名から CPU / DIMM / Fan / PSU の Component を生成する。

    FRU では得られないコンポーネント存在情報をセンサーから補完する。
    センサーは名前のみで詳細スペックは不明なため part_id / serial は空。
    """
    try:
        sensors = list(cmd.get_sensor_data())
    except Exception as e:
        logger.warning("IPMI get_sensor_data failed: %s", e)
        return []

    cpus: set[str] = set()
    dimms: set[str] = set()
    fans: set[str] = set()
    psus: set[str] = set()

    for s in sensors:
        name = getattr(s, "name", "") or ""
        stype = getattr(s, "type", "") or ""
        states = getattr(s, "states", []) or []

        # CPU: "CPU1 Temp" (Supermicro) or type=Processor "CPU0_Status" (Gigabyte 等)
        if _re.match(r"CPU\d+\s+Temp", name, _re.IGNORECASE):
            cpus.add(_re.match(r"CPU(\d+)", name, _re.IGNORECASE).group(1))
        elif stype == "Processor":
            m = _re.search(r"CPU(\d+)", name, _re.IGNORECASE)
            cpus.add(m.group(1) if m else "0")

        # P1-DIMMA1 Temp / P2-DIMMB2 Temp → Memory slot names
        elif _re.match(r"P\d+-DIMM\w+\s+Temp", name, _re.IGNORECASE):
            slot = _re.match(r"(P\d+-DIMM\w+)", name, _re.IGNORECASE).group(1)
            dimms.add(slot)

        # Fan sensors
        elif stype == "Fan" and getattr(s, "value", None) is not None:
            fans.add(name)

        # PSU: Power Supply sensors with "Present" state
        elif stype == "Power Supply" and any("Present" in st for st in states):
            psus.add(name)

    out: list[Component] = []
    for num in sorted(cpus, key=int):
        # ponytail: use sensor number as-is; Supermicro is 1-based but normalizer re-indexes anyway
        out.append(Component(kind="cpu", name=f"CPU {num}"))
    for slot in sorted(dimms):
        out.append(Component(kind="memory", name=slot))
    for fname in sorted(fans):
        out.append(Component(kind="fan", name=fname))
    for pname in sorted(psus):
        out.append(Component(kind="psu", name=pname))

    logger.debug("sensor-derived components: %d cpu, %d dimm, %d fan, %d psu",
                 len(cpus), len(dimms), len(fans), len(psus))
    return out


def _guess_kind(fru_name: str) -> str:
    n = fru_name.lower()
    if "psu" in n or "power" in n:
        return "psu"
    if "fan" in n:
        return "fan"
    if "nic" in n or "net" in n:
        return "nic"
    return "other"
