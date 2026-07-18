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
    asset_tag: str = ""
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


@dataclass
class BmcNetworkInterface:
    """BMC (管理コントローラ) 自身のネットワーク設定 (インターフェース1枚分)。

    get_network_config() は BMC が持つ複数のインターフェース (専用ポート/
    ホストと共有するポート/ボンディング等) をそれぞれ返すため list[BmcNetworkInterface]
    を戻す。InventoryResult とは別に、Power Status と同様にページ表示のたびに
    ライブ取得する (DB には保存しない)。
    """
    name: str = ""
    dhcp_enabled: bool | None = None
    ipv4_address: str = ""
    ipv4_subnet_mask: str = ""
    ipv4_gateway: str = ""
    ipv6_addresses: list[str] = field(default_factory=list)
    ipv6_gateway: str = ""
    dns_servers: list[str] = field(default_factory=list)
    mac_address: str = ""
    hostname: str = ""
    fqdn: str = ""
    vlan_id: int | None = None
    vlan_enabled: bool | None = None
    link_status: str = ""


@dataclass
class ManagerInfo:
    """BMC (管理コントローラ) 自身のファームウェア/ヘルス情報。

    get_manager_info() の戻り値。firmware_version は滅多に変わらないため
    BuildModulesView の Inventory スキャンで detected_firmware_version に保存され、
    health は変化しうるため ManagerHealthSyncJob / ScheduledManagerHealthSyncJob が
    独立して BMCEndpoint.manager_health に保存する。
    """
    firmware_version: str = ""
    health: str = ""
    model: str = ""
    name: str = ""


@dataclass
class SensorReading:
    """温度・電圧・消費電力・Fan回転数などのセンサー実測値。

    get_sensors() の戻り値。SensorsSyncJob / ScheduledSensorsSyncJob が
    BMCEndpoint.sensors に dataclasses.asdict() でシリアライズして保存する。
    """
    name: str
    kind: str               # temperature | fan | voltage | power
    value: float | None = None
    units: str = ""
    status: str = ""


@dataclass
class SelEntry:
    """System Event Log (SEL) の1エントリ。

    get_event_log() の戻り値。EventLogSyncJob / ScheduledEventLogSyncJob が
    BMCEndpoint.event_log に dataclasses.asdict() でシリアライズして保存する。
    """
    created: str = ""
    severity: str = ""
    message: str = ""
    sensor_type: str = ""
