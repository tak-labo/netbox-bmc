"""
正規化インベントリ表現。

すべてのドライバ (Redfish / IPMI) はこの中間表現を返す。
sync.py はこの表現だけを見て NetBox オブジェクトへマッピングするため、
ベンダー差分・プロトコル差分はドライバ層で完全に吸収される。
"""
from dataclasses import dataclass, field


@dataclass
class SystemInfo:
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    sku: str = ""           # サービスタグ / 製品番号
    uuid: str = ""
    bios_version: str = ""
    power_state: str = ""
    hostname: str = ""


@dataclass
class Component:
    """CPU / DIMM / ドライブ / NIC / PSU などの個別部品。"""
    kind: str               # cpu | memory | drive | nic | psu | fan | firmware
    name: str               # 一意な名前 (例: "CPU.Socket.1", "DIMM.A1")
    manufacturer: str = ""
    part_id: str = ""       # 型番 / モデル
    serial: str = ""
    description: str = ""   # 容量・速度などの人間向け情報
    firmware: str = ""
    extra: dict = field(default_factory=dict)
    source_path: str = ""   # 取得元 Redfish パス (例: /redfish/v1/Systems/1/Processors/CPU1)


@dataclass
class InventoryResult:
    system: SystemInfo
    components: list[Component] = field(default_factory=list)
    vendor: str = ""        # 検出したベンダー名 (Dell, HPE, Lenovo, ...)
    protocol: str = ""      # redfish | ipmi
    raw: dict = field(default_factory=dict)  # デバッグ用の生データ(任意)
