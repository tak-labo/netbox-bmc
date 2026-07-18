# netbox-bmc 詳細設計書

本書は `netbox_bmc` プラグインの内部設計を、コードから読み取れる実装事実に基づいて記述する
詳細設計書である。要約された方針は `CLAUDE.md` を参照。ここでは各レイヤの責務・データフロー・
主要シーケンスを図とともに掘り下げる。

## 目次

1. [全体アーキテクチャ](#1-全体アーキテクチャ)
2. [プロトコル自動検出](#2-プロトコル自動検出)
3. [ドライバ層](#3-ドライバ層)
4. [データモデル (BMCEndpoint)](#4-データモデル-bmcendpoint)
5. [認証情報解決](#5-認証情報解決)
6. [Module インベントリ同期](#6-module-インベントリ同期)
7. [バックグラウンド同期の2系統](#7-バックグラウンド同期の2系統)
8. [Device 画面への統合](#8-device-画面への統合)
9. [URL / View 一覧](#9-url--view-一覧)
10. [REST API](#10-rest-api)
11. [i18n](#11-i18n)
12. [既知の制限](#12-既知の制限)

---

## 1. 全体アーキテクチャ

レイヤ分離が設計の中心にある。ドライバ層は NetBox / Django を一切知らず、
中間表現(`inventory.py`)だけを返す。NetBox への書き込みは Normalizer / Sync / Job 層が担う。

```mermaid
flowchart LR
    subgraph BMC["BMC (物理)"]
        RF["Redfish\n/redfish/v1"]
        WSM["WS-MAN\nIntel AMT :16992/16993"]
        IPMI["IPMI\n(RMCP+)"]
    end

    subgraph Drivers["drivers/"]
        Base["base.py\ndetect_and_build()"]
        RFD["redfish.py\nRedfishDriver +\nDell/HPE/Lenovo/AMI サブクラス"]
        AMTD["amt.py\nIntelAmtDriver"]
        IPMID["ipmi.py\nIPMIDriver (pyghmi)"]
    end

    subgraph Mid["中間表現 (inventory.py)"]
        IR["InventoryResult / Component"]
        NET["BmcNetworkInterface"]
        MI["ManagerInfo"]
        SR["SensorReading"]
        SEL["SelEntry"]
    end

    subgraph App["アプリケーション層"]
        Norm["normalizer.py\nNormalizedComponent"]
        MSync["module_sync.py\nModule/ModuleBay/ModuleType 差分同期"]
        Jobs["jobs.py\n各種 *SyncJob"]
        Views["views.py / urls.py"]
    end

    subgraph NB["NetBox"]
        Device["dcim.Device"]
        Module["dcim.Module\n(bmc-synced タグ)"]
        BMCEndpoint["netbox_bmc.BMCEndpoint\n(DB)"]
    end

    RF --> RFD
    WSM --> AMTD
    IPMI --> IPMID
    Base --> RFD & AMTD & IPMID
    RFD & AMTD & IPMID --> IR & NET & MI & SR & SEL
    IR --> Norm --> MSync --> Module
    NET & MI & SR & SEL --> Jobs --> BMCEndpoint
    Views --> Base
    BMCEndpoint -. "1:1" .-> Device
```

**重要な不変条件**

- ドライバ層 (`drivers/`) は NetBox を import しない。戻り値は `inventory.py` のデータクラスのみ。
- Module 同期の差分管理は `bmc-synced` タグで分離する。手動作成 Module には触れない。
- Redfish のパスはハードコードせず `ServiceRoot` からのリンク探索で得る(ベンダー間のパス差分を
  コード変更なしに吸収するための設計)。

---

## 2. プロトコル自動検出

`BMCEndpoint.protocol` が `auto` の場合、`drivers/base.py:detect_and_build()` が以下の順で
プロービングする。

```mermaid
flowchart TD
    Start(["detect_and_build(protocol='auto')"]) --> ProbeRF{"probe_redfish()\nGET /redfish/v1\n(5秒タイムアウト)"}
    ProbeRF -- "応答あり" --> BuildRF["build_redfish_driver()\n→ ServiceRoot の Vendor/Oem を見て\nDell/HPE/Lenovo/AMI サブクラスへ\ndispatch (該当なければ汎用 RedfishDriver)"]
    ProbeRF -- "応答なし" --> PortCheck{"port 未指定?"}
    PortCheck -- "Yes" --> ProbeAMT{"probe_amt()\nWS-MAN :16993 (AMT固定ポート)"}
    PortCheck -- "No" --> IPMIDriver["IPMIDriver\n(pyghmi RMCP+)"]
    ProbeAMT -- "応答あり" --> AMTDriver["IntelAmtDriver"]
    ProbeAMT -- "応答なし" --> IPMIDriver
    BuildRF --> Done(["BaseDriver インスタンス"])
    AMTDriver --> Done
    IPMIDriver --> Done
```

`protocol` が `redfish` / `ipmi` / `wsman` に明示指定されている場合はプロービングをスキップし、
該当ドライバを直接構築する。

---

## 3. ドライバ層

### 3.1 BaseDriver インターフェース (`drivers/base.py`)

全ドライバ共通の抽象メソッド。未対応の機能は `NotImplementedError` を送出する
(呼び出し側の View / Job はこれを捕捉して「このプロトコルでは未対応」として扱う)。

| メソッド | 用途 | 対応状況 |
|---|---|---|
| `get_inventory()` | CPU/Memory/Drive/PSU/Fan/PCI/Firmware 一式取得 | Redfish, IPMI, AMT(一部) |
| `get_power_state()` / `set_power(action)` | 電源状態取得・操作 | Redfish, IPMI |
| `get_network_config()` | BMC 自身の NIC 設定一覧(複数可) | Redfish, IPMI |
| `get_manager_info()` | BMC ファームウェア/ヘルス | Redfish, IPMI |
| `set_identify(on)` | Identify LED 点灯/消灯 | Redfish, IPMI |
| `get_sensors()` | 温度/Fan/電圧/消費電力の実測値 | Redfish, IPMI |
| `get_event_log(limit)` | System Event Log 直近 N 件 | Redfish, IPMI |

### 3.2 Redfish ドライバ (`drivers/redfish.py`)

```mermaid
classDiagram
    class RedfishDriver {
        +vendor: str = "Generic"
        +get_inventory()
        +get_power_state()
        +set_power(action)
        +get_network_config()
        +get_manager_info()
        +set_identify(on) ETag/If-Match対応
        +get_sensors()
        +get_event_log(limit)
        #_get(path) / _get_optional(path)
        #_collection(resource, key)
        #_collect_psu(sysres) Chassis経由
        #_collect_fans(sysres) Chassis経由
        #_collect_pcie_devices(sysres) PCIeDevices経由
        #detect_vendor(root)$
    }
    class DellRedfishDriver {
        +vendor = "Dell"
    }
    class HPERedfishDriver {
        +vendor = "HPE"
    }
    class LenovoRedfishDriver {
        +vendor = "Lenovo"
    }
    class AmiRedfishDriver {
        +vendor = "AMI"
        +get_inventory() FruInfoで補完
        #_collect_pcie_devices() Chassis配下に上書き
    }
    RedfishDriver <|-- DellRedfishDriver
    RedfishDriver <|-- HPERedfishDriver
    RedfishDriver <|-- LenovoRedfishDriver
    RedfishDriver <|-- AmiRedfishDriver
```

- パス探索は `ServiceRoot`(`/redfish/v1`) → `Systems`/`Managers`/`Chassis` の各コレクションを
  辿る方式で、ベンダー固有 URI を直書きしない。
- PSU/Fan/センサー(温度・電圧・消費電力)は `Systems[0].Links.Chassis` を辿った先の
  `Thermal` / `Power` リソースから取得する。
- ネットワーク設定は **`Managers/{id}/EthernetInterfaces`** から取得する
  (`Systems/{id}/EthernetInterfaces` はホスト OS 側の NIC であり別物なので注意)。
  USB ガジェット系インターフェース(`usb0` 等)は一覧から除外する。IPv4/IPv6 両方に対応。
  複数インターフェース(専用ポート/ホスト共有ポート/ボンディング等)を list で返す。
- Identify LED は `Chassis.LocationIndicatorActive` を PATCH する。ETag(`@odata.etag` または
  HTTP `ETag` ヘッダ)を `If-Match` として送信し、`HTTP 428 Precondition Required` を返す
  厳格な実装(Dell iDRAC 系)にも対応する。PATCH が拒否された場合は旧スキーマの
  `IndicatorLED` 文字列 enum にフォールバックする。
- ベンダー検出は `ServiceRoot` の `Vendor` / `Oem` キーを見て `VENDOR_DRIVERS` マップから
  サブクラスへ差し替える(`build_redfish_driver()`)。該当ベンダーがなければ汎用
  `RedfishDriver` のまま続行する(例外にしない)。

### 3.3 IPMI ドライバ (`drivers/ipmi.py`)

`pyghmi` (RMCP+) ベース。ファームウェアバージョンは標準 "Get Device ID" raw コマンド
(`netfn=0x06, command=0x01`)で取得し、ベンダー拡張には依存しない。ヘルスは
`pyghmi` の `get_health()`(内部で `get_sensor_data()` を集約)を利用する。
ネットワーク設定は `get_net_configuration()` / `get_net6_configuration()` を使い、
IPv6 はベストエフォート(取得失敗時は空のまま継続)。

### 3.4 Intel AMT ドライバ (`drivers/amt.py`)

WS-MAN (SOAP/XML over HTTP) を直接叩く実装で、追加ライブラリなし(`requests` + 標準の
`xml.etree.ElementTree`)。HTTP Digest 認証、ポート 16992(HTTP)/16993(HTTPS) 固定。
CPU/Memory/AMT ファームウェアバージョンの取得に対応(AMT 6.0 以降 = vPro 第1世代以降)。

---

## 4. データモデル (BMCEndpoint)

`BMCEndpoint` は `Device` と 1:1 の `OneToOneField`。フィールドは用途ごとに明確なグループに
分かれている。

```mermaid
erDiagram
    Device ||--|| BMCEndpoint : "1:1"
    IPAddress ||--o{ BMCEndpoint : "管理IP"

    BMCEndpoint {
        int device_id FK "OneToOne CASCADE"
        int ip_address_id FK "PROTECT"
        int port "nullable"
        string protocol "auto or redfish or wsman or ipmi"
        bool verify_ssl
        string username "平文フォールバック用"
        string password "平文フォールバック用"
        string detected_vendor
        string detected_protocol
        string detected_serial
        string detected_firmware_version "Inventoryスキャンで取得"
        datetime last_sync "Inventoryスキャンの最終実行日時"
        string last_sync_status "OK or Error"
        json network_interfaces "list of BmcNetworkInterface"
        datetime network_last_sync
        json sensors "list of SensorReading"
        datetime sensors_last_sync
        json event_log "list of SelEntry"
        datetime event_log_last_sync
        string manager_health
        datetime manager_health_last_sync
    }
```

フィールドグループの意味:

| グループ | フィールド | 更新経路 |
|---|---|---|
| 接続設定 | `device`, `ip_address`, `port`, `protocol`, `verify_ssl` | ユーザーが Add/Edit フォームで設定 |
| 認証情報 (フォールバック) | `username`, `password` | netbox-secrets 未使用時のみ参照 (§5) |
| Inventory スキャン結果 | `detected_vendor`, `detected_protocol`, `detected_serial`, `detected_firmware_version`, `last_sync`, `last_sync_status` | `BuildModulesView`(「Build Modules」ボタン) |
| Network | `network_interfaces`, `network_last_sync` | `NetworkSyncJob` / `ScheduledNetworkSyncJob` |
| Sensors | `sensors`, `sensors_last_sync` | `SensorsSyncJob` / `ScheduledSensorsSyncJob` |
| Event Log | `event_log`, `event_log_last_sync` | `EventLogSyncJob` / `ScheduledEventLogSyncJob` |
| Manager Health | `manager_health`, `manager_health_last_sync` | `ManagerHealthSyncJob` / `ScheduledManagerHealthSyncJob` |

`detected_firmware_version` だけ「Inventory スキャン結果」グループに属する点に注意
(§7 で理由を説明)。Power Status は DB に保存されない(常にライブ取得)。

---

## 5. 認証情報解決

`BMCEndpoint.get_driver(request=None)` がドライバ生成の唯一の入口。認証情報の解決は
`credentials.py:get_credential()` が担う。netbox-secrets のセットアップ手順・実際の
動作検証手順は [NETBOX_SECRETS.md](NETBOX_SECRETS.md) を参照。

```mermaid
flowchart TD
    Start(["get_credential(endpoint, request)"]) --> TrySecrets{"netbox-secrets\nインストール済み?"}
    TrySecrets -- "No (ImportError)" --> Fallback["平文フォールバック\nendpoint.username / password"]
    TrySecrets -- "Yes" --> FindSecret{"SecretRole='bmc-credentials' の\nSecret が Device に紐づいているか"}
    FindSecret -- "No" --> Fallback
    FindSecret -- "Yes" --> HasRequest{"request が渡されたか"}
    HasRequest -- "Yes (UI操作)" --> SessionKey["Cookie/X-Session-Key ヘッダの\nセッションキーで UserKey を復号"]
    HasRequest -- "No (バックグラウンドジョブ)" --> ServiceAccount["PLUGINS_CONFIG.service_account の\nRSA秘密鍵(PEM)で UserKey を復号"]
    SessionKey --> Decrypt["master_key で Secret.decrypt()"]
    ServiceAccount --> Decrypt
    Decrypt -- "成功" --> UseSecret["username=Secret.name\npassword=Secret.plaintext"]
    Decrypt -- "失敗 (例外)" --> Fallback
    UseSecret --> Done(["Credential"])
    Fallback --> Done
```

**Secret のレイアウト規約**

- `SecretRole.slug == "bmc-credentials"`
- `Secret.name` = BMC ユーザー名(非暗号化フィールド)
- `Secret.plaintext` = BMC パスワード(RSA 暗号化)
- `assigned_object` = 当該 `BMCEndpoint.device`

バックグラウンドジョブ(`request=None`)経路でセッションキーを使わない理由: ジョブの
`kwargs` を介してセッションキーを渡すと Job レコードに平文で残ってしまうため。
そのためサービスアカウントの RSA 秘密鍵を使う経路のみを実装している。

---

## 6. Module インベントリ同期

「Build Modules」ボタン(`BuildModulesView`)を起点に、スキャン → プレビュー → 適用の
3ステップで進む(即時同期。バックグラウンドジョブ化はしていない)。

```mermaid
sequenceDiagram
    participant U as ユーザー
    participant V1 as BuildModulesView (POST)
    participant D as Driver
    participant Sess as request.session
    participant V2 as BuildModulesPreviewView (GET)
    participant V3 as BuildModulesApplyView (POST)
    participant NB as NetBox (Module/ModuleBay/ModuleType)

    U->>V1: 「Build Modules」クリック
    V1->>D: get_inventory()
    D-->>V1: InventoryResult
    V1->>D: get_manager_info() (ベストエフォート)
    D-->>V1: firmware_version
    V1->>V1: detected_vendor/protocol/serial,\ndetected_firmware_version,\nlast_sync, last_sync_status を保存
    V1->>V1: normalize(components) → compute_diff(device, ncs)
    V1->>Sess: entries/firmware/vendor/protocol を保存
    V1-->>U: redirect → プレビューへ

    U->>V2: プレビューページ表示
    V2->>Sess: セッションからentries読込
    V2-->>U: 種別フィルタ付きdiffテーブル\n(new/updated/unchanged/removed バッジ)

    U->>V3: 選択項目にチェック→「Apply」
    V3->>Sess: セッションからentries読込
    V3->>NB: apply_module_sync()\n(bmc-syncedタグ付きModuleのみ作成/更新/削除)
    V3->>NB: apply_firmware_to_device()\n(Device.custom_field_data.bmc_firmware_inventory)
    V3-->>U: 結果メッセージ表示
```

`compute_diff()` は既存の `bmc-synced` タグ付き `Module` と検出コンポーネントを
`normalized_name` で突き合わせ、`new` / `updated` / `unchanged` / `removed` の4状態に分類する。
`ModuleBay` が存在しない場合は `new` エントリとして扱われ、適用時に自動作成される。

---

## 7. バックグラウンド同期の2系統

BMC から取得するデータは「変化頻度」によって扱いが分かれる、という設計判断がある。

```mermaid
flowchart TB
    subgraph Live["① 即時ライブ取得 (DB非保存)"]
        PS["Power Status"]
        PSNote["電源操作直後に古い状態を\n見せないため、ページ表示の\nたびに直接取得"]
    end

    subgraph Persisted["② DB永続化 + バックグラウンドジョブ"]
        direction TB
        Btn["Sync ボタン (POST)"] --> AV["*SyncActionView"]
        AV -->|"enqueue"| Job["*SyncJob (JobRunner)"]
        Job -->|"get_driver() → 取得"| Helper["_sync_*() ヘルパー"]
        Helper -->|"save(update_fields=...)"| DB[("BMCEndpoint\n(DB)")]
        DB --> Page["ページはDB値を表示するだけ"]
        Sched["Scheduled*SyncJob\n(全エンドポイント一括,\nPLUGINS_CONFIG の\n*_sync_interval_minutes>0で有効)"] --> Helper
    end

    PS -.->|"対比"| Persisted
```

対象と対応するジョブ:

| データ | Job (手動/ボタン) | Scheduled Job (全台一括) | 保存先フィールド |
|---|---|---|---|
| Network | `NetworkSyncJob` | `ScheduledNetworkSyncJob` | `network_interfaces` / `network_last_sync` |
| Sensors | `SensorsSyncJob` | `ScheduledSensorsSyncJob` | `sensors` / `sensors_last_sync` |
| Event Log | `EventLogSyncJob` | `ScheduledEventLogSyncJob` | `event_log` / `event_log_last_sync` |
| Manager Health | `ManagerHealthSyncJob` | `ScheduledManagerHealthSyncJob` | `manager_health` / `manager_health_last_sync` |
| BMC Firmware | (専用ジョブなし) | (専用ジョブなし) | `detected_firmware_version` ※Inventoryスキャンで更新 |

**なぜ BMC Firmware だけ専用ジョブを持たないか**: ファームウェアバージョンは滅多に変わらない
ため、専用の定期ジョブを持つコストに見合わない。そのため「Build Modules」実行時の
Inventory スキャンに相乗りさせて `detected_firmware_version` を更新する。一方 BMC Health は
ハードウェア状態次第で変化しうるため、独立した `ManagerHealthSyncJob` を持つ。

**Sync Status カードの紛らわしさ対策**: 上記いずれとも別に、Sync Status カードには
「Inventory Last Sync」「Inventory Scan Status」という行がある。これは `last_sync` /
`last_sync_status` フィールド、すなわち Module インベントリスキャンの実行結果であり、
Network/Sensors/Event Log/Health の同期時刻とは無関係。UI 上で紛らわしいため、意図的に
「Inventory」を冠したラベルにして区別している。

**Scheduled Job の冪等性**: `NetBoxBMCConfig.ready()` は Web/Worker プロセス起動のたびに
呼ばれるため、`_enqueue_scheduled_job()` は同名の Job が `pending`/`scheduled`/`running` で
既に存在する場合は登録をスキップする。マイグレーション未適用(Job テーブル未作成)の場合は
`DatabaseError` を握りつぶして何もしない。

---

## 8. Device 画面への統合

`template_content.py:DeviceBMCPanel` (`PluginTemplateExtension`, `models=["dcim.device"]`) が
Device 詳細画面に2箇所フックする。

```mermaid
flowchart LR
    Device["Device 詳細画面"] --> Buttons["buttons()\n→ 上部ボタン列\n(Edit/Clone/Delete と同じ行)"]
    Device --> RightPage["right_page()\n→ 右カラムのパネル"]
    Buttons --> HasEP{"device.bmc_endpoint\nが存在する?"}
    RightPage --> HasEP
    HasEP -- "Yes" --> ShowButton["「View BMC Endpoint」ボタン表示\n(device_bmc_button.html)"]
    HasEP -- "Yes" --> ShowPanel["BMC情報パネル表示\n(device_bmc_panel.html)"]
    HasEP -- "No" --> Hide["何も表示しない"]
```

`BMCEndpoint` が存在しない Device には何も注入しない(`_get_bmc_endpoint()` が
`device.bmc_endpoint` の `RelatedObjectDoesNotExist` を捕捉して `None` を返す)。

---

## 9. URL / View 一覧

```mermaid
flowchart LR
    subgraph CRUD["CRUD (netbox.views.generic)"]
        L["/endpoints/\nBMCEndpointListView"]
        A["/endpoints/add/\nBMCEndpointEditView"]
        D["/endpoints/pk/\nBMCEndpointView"]
        E["/endpoints/pk/edit/\nBMCEndpointEditView"]
        Del["/endpoints/pk/delete/\nBMCEndpointDeleteView"]
    end

    subgraph Scan["Inventoryスキャン"]
        BM["/build-modules/\nPOST: スキャン実行"]
        BMP["/build-modules/preview/\nGET: 差分プレビュー"]
        BMA["/build-modules/apply/\nPOST: 適用"]
    end

    subgraph Live["即時アクション"]
        Pw["/power/\nPOST: 電源操作"]
        Id["/identify/\nPOST: Identify LED"]
        PwS["/power-status/\nGET: 電源状態JSON (ライブ)"]
        Test["/test-connection/\nPOST: 保存前の疎通確認"]
        Raw["/raw/\nGET: Redfish生JSON (デバッグ)"]
    end

    subgraph SyncBtn["Sync ボタン (POST → ジョブenqueue)"]
        NS["/network-sync/"]
        SS["/sensors-sync/"]
        ES["/event-log-sync/"]
        MS["/manager-health-sync/"]
    end
```

---

## 10. REST API

`api/` 配下に `BMCEndpoint` の CRUD のみを提供する `NetBoxModelViewSet` がある
(`NetBoxRouter` 経由で `/api/plugins/bmc/endpoints/` に公開)。

- `BMCEndpointSerializer`: `device`, `ip_address`, `port`, `protocol`, `verify_ssl`,
  `username`, `password`(write_only), `detected_vendor`, `detected_protocol`,
  `last_sync`, `last_sync_status`, `tags`, `custom_fields` を公開。
- 同期トリガー(Sync ボタン相当)やセンサー/イベントログ/ネットワークの参照系エンドポイントは
  REST API 上には未提供(UI 上のジョブ enqueue のみ)。

---

## 11. i18n

- 全 UI 文字列は `gettext_lazy as _`(Python)/ `{% trans %}`(テンプレート)でラップし、
  `netbox_bmc/locale/ja/LC_MESSAGES/django.po` に対訳を追加する。
- `Meta.verbose_name` のように Django が naive に `+ "s"` で複数形を作る箇所は **翻訳しない**
  (翻訳すると "BMCエンドポイントs" のような壊れた複数形になるため、`BMCEndpoint.Meta`
  の `verbose_name` は意図的に英語のまま)。
- `.mo` はバイナリのため `git merge` でコンフリクトしやすい。コンフリクト時は必ず
  マージ後の `.po` から再コンパイルする。

---

## 12. 既知の制限

- マルチノードシャーシ(`Systems` が複数存在する構成)は未対応。
- 定期一括 **Module** 同期(`ScheduledInventorySyncJob`)は未実装のスタブ
  (Network/Sensors/Event Log/Manager Health の定期同期は実装済み)。
- KVM / SOL コンソールは旧プラグイン (`netbox-ipmi-plugin`) から意図的に未移植。
- Redfish 準拠度の低い古い BMC(HPE iLO 4 等)での動作は未検証。
- REST API は `BMCEndpoint` の CRUD のみ。同期トリガーや参照系は未提供。
