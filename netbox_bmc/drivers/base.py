"""
ドライバ基底クラスとプロトコル/ベンダー自動検出。

設計方針:
- BaseDriver は最小限のインターフェイスのみ定義
- Redfish はパスをハードコードせず ServiceRoot からリンクを辿る
- ベンダー固有処理 (OEM 拡張) はベンダーサブクラスでオーバーライド
"""
from __future__ import annotations

from ..inventory import InventoryResult


class BMCError(Exception):
    """ドライバ層の共通例外。"""


class BaseDriver:
    protocol: str = ""

    def __init__(self, address: str, username: str, password: str,
                 port: int | None = None, verify_ssl: bool = False,
                 timeout: int = 15):
        self.address = address
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self.timeout = timeout

    # --- 必須インターフェイス -------------------------------------------
    def get_inventory(self) -> InventoryResult:
        raise NotImplementedError

    def get_power_state(self) -> str:
        raise NotImplementedError

    def set_power(self, action: str) -> None:
        """action: on | off | cycle | reset | soft"""
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def detect_and_build(address: str, username: str, password: str,
                     protocol: str = "auto", **kwargs) -> BaseDriver:
    """
    プロトコルを判別してドライバインスタンスを返す。

    auto の場合: まず https://<addr>/redfish/v1 を叩き、応答があれば
    Redfish、なければ IPMI へフォールバックする。
    """
    from .redfish import RedfishDriver, probe_redfish, build_redfish_driver
    from .ipmi import IPMIDriver

    if protocol == "redfish":
        return build_redfish_driver(address, username, password, **kwargs)
    if protocol == "ipmi":
        return IPMIDriver(address, username, password, **kwargs)

    # auto
    if probe_redfish(address, timeout=5, verify_ssl=kwargs.get("verify_ssl", False)):
        return build_redfish_driver(address, username, password, **kwargs)
    return IPMIDriver(address, username, password, **kwargs)
