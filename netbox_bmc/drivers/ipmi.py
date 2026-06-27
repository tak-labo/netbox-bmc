"""
IPMI ドライバ (レガシー BMC 向けフォールバック)。

pyghmi の get_inventory() で FRU 情報を取得する。
Redfish より取得できる情報は限定的 (CPU/DIMM の詳細は出ないことが多い)。
既存 netbox-ipmi-plugin の電源操作・SOL 周りはここに段階的に移植する。
"""
from __future__ import annotations

import logging

from ..inventory import Component, InventoryResult, SystemInfo
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


class IPMIDriver(BaseDriver):
    protocol = "ipmi"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            from pyghmi.ipmi import command
        except ImportError as e:
            raise BMCError("pyghmi is not installed") from e
        try:
            self.cmd = command.Command(
                bmc=self.address,
                userid=self.username,
                password=self.password,
                port=self.port or 623,
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
                system.model = (info.get("Product name")
                                or info.get("Board product name") or "")
                system.serial = (info.get("Serial Number")
                                 or info.get("Board serial number") or "")
                system.uuid = str(info.get("UUID") or "")
            else:
                components.append(Component(
                    kind=_guess_kind(name),
                    name=name,
                    manufacturer=info.get("Manufacturer", "") or "",
                    part_id=info.get("Part Number", "")
                            or info.get("Product name", "") or "",
                    serial=info.get("Serial Number", "") or "",
                ))

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

    def close(self):
        try:
            self.cmd.ipmi_session.logout()
        except Exception:
            pass


def _guess_kind(fru_name: str) -> str:
    n = fru_name.lower()
    if "psu" in n or "power" in n:
        return "psu"
    if "fan" in n:
        return "fan"
    if "nic" in n or "net" in n:
        return "nic"
    return "other"
