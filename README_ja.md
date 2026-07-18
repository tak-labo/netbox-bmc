# netbox-bmc

[![NetBox](https://img.shields.io/badge/NetBox-4.5%20|%204.6-blue)](https://github.com/netbox-community/netbox)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

[English](README.md)

NetBox 向けアウトオブバンド管理統合プラグイン。  
Redfish / IPMI 経由のインベントリ同期・電源操作を提供します。

## 対応プロトコル / ベンダー

| プロトコル | 対応ベンダー |
|---|---|
| Redfish | Dell iDRAC, HPE iLO, Lenovo XCC, Supermicro, AMI, Generic |
| WS-MAN | Intel AMT (vPro) |
| IPMI | IPMI 対応 BMC 全般（フォールバック） |

プロトコルは自動検出します。まず `/redfish/v1` を probe し、次に WS-MAN ポート 16993（Intel AMT）を probe し、失敗した場合 IPMI にフォールバックします。

## テスト済みハードウェア

| メーカー | モデルシリーズ | BMC | プロトコル | 状態 |
|---|---|---|---|---|
| Dell | PowerEdge | iDRAC 9 | Redfish | 動作見込み |
| HPE | ProLiant | iLO 5 | Redfish | 動作見込み |
| HPE | ProLiant | iLO 6 | Redfish | 動作見込み |
| Lenovo | ThinkSystem | XCC2 / XCC3 | Redfish | 動作見込み |
| Supermicro | X12 / X13 | BMC | Redfish | 動作見込み |
| AMI | ASMB 搭載サーバー | AMI Redfish Server | Redfish | 動作見込み |
| Intel | vPro 対応デスクトップ / ワークステーション | AMT 6.0+ | WS-MAN | 動作見込み |
| Generic | — | IPMI 対応 BMC 全般 | IPMI | 動作見込み（フォールバック） |

## 機能

- **Module ビルダー**: BMC のハードウェアインベントリを NetBox Module に同期
  - Redfish スキャン → 差分バッジ（新規 / 更新あり / 変更なし / 削除候補）付きでプレビュー表示
  - 適用前に個別チェックボックスで登録コンポーネントを選択
  - ModuleBay が存在しない場合は自動作成（プレビューで事前通知）
  - FRU 交換後のシリアル変更を検出して差分更新
  - `bmc-synced` タグ付き Module のみ管理。手動登録 Module には触れない
- **収集コンポーネント**: CPU / Memory / Drive / PSU / Fan / Firmware / PCI デバイス
  - PSU・Fan は Chassis リンク経由、PCIe は PCIeDevices コレクション経由
- **ベンダー自動検出**: ServiceRoot の `Vendor` / `Oem` キーから Dell / HPE / Lenovo / AMI サブクラスドライバへディスパッチ
- **電源操作**: on / off / soft / cycle / reset（両プロトコル対応）
- **Identify LED**: シャーシの Identify ランプを点灯/消灯（ETag/`If-Match` 事前条件を要求する厳格な Redfish 実装にも対応）
- **BMC ネットワーク設定**: BMC 自身の全ネットワークインターフェース（1つだけでなく複数）を表示。IPv4/IPv6 アドレス・ゲートウェイ、DHCP 状態、VLAN、DNS サーバーを含む。USB ガジェット系インターフェースは除外
- **センサーテレメトリ**: 温度・Fan回転数・電圧・消費電力の実測値
- **System Event Log (SEL)**: BMC の直近のイベントログエントリ
- **BMC ヘルス・ファームウェア**: BMC のヘルス状態とファームウェアバージョン
- **バックグラウンド同期ジョブ**: Network / Sensors / Event Log / BMC Health は DB に永続化され、エンドポイントごとの「Sync」ボタン、または任意で定期ジョブ（[設定](#設定)参照）により更新されます。画面表示のたびに BMC へ問い合わせるのではなく DB の値を表示します。BMC Firmware は滅多に変わらないため、専用の Sync ボタンではなく Inventory スキャンの一部として更新されます
- **接続テスト (Test Connection)**: BMC Endpoint 保存前にプロトコル・認証情報を検証
- **Device Role フィルター**: BMC Endpoint 追加時に Device 候補を Role で絞り込み
- **Device 画面連携**: BMC Endpoint が存在する Device の画面には「View BMC Endpoint」ボタンとステータスパネルが自動的に表示されます
- **REST API**: `/api/plugins/bmc/endpoints/` から `BMCEndpoint` の CRUD が可能
- **英語 / 日本語 UI**（i18n）

## インストール

### 標準環境（非 Docker）

```bash
pip install netbox-bmc
python manage.py migrate
```

`configuration.py` に追記：

```python
PLUGINS = ["netbox_bmc"]
PLUGINS_CONFIG = {
    "netbox_bmc": {
        "sync_interval_minutes": 0,
        "default_verify_ssl": False,
    },
}
```

### Docker 環境（netbox-docker）

[公式プラグインインストールガイド](https://github.com/netbox-community/netbox-docker/wiki/Using-Netbox-Plugins) に準拠した手順です。

**`plugin_requirements.txt`**
```
netbox-bmc
```

**`Dockerfile-Plugins`**
```dockerfile
FROM netboxcommunity/netbox:latest

COPY ./plugin_requirements.txt /opt/netbox/
RUN /usr/local/bin/uv pip install -r /opt/netbox/plugin_requirements.txt
```

**`docker-compose.override.yml`**
```yaml
services:
  netbox:
    image: netbox:latest-plugins
    pull_policy: never
    build:
      context: .
      dockerfile: Dockerfile-Plugins
  netbox-worker:
    image: netbox:latest-plugins
    pull_policy: never
```

**`configuration/plugins.py`**
```python
PLUGINS = ["netbox_bmc"]
PLUGINS_CONFIG = {
    "netbox_bmc": {
        "sync_interval_minutes": 0,
        "default_verify_ssl": False,
    },
}
```

ビルドして起動：
```bash
docker compose build --no-cache
docker compose up -d
```

## 設定

`configuration.py` の `PLUGINS_CONFIG["netbox_bmc"]` で設定します：

| キー | デフォルト | 説明 |
|---|---|---|
| `sync_interval_minutes` | `0` | 定期一括 Module インベントリ同期の間隔（分）。`0` で無効。未実装のスタブジョブ。 |
| `network_sync_interval_minutes` | `0` | 定期一括ネットワーク設定同期の間隔（分）。`0` で無効。 |
| `sensors_sync_interval_minutes` | `0` | 定期一括センサー同期の間隔（分）。`0` で無効。 |
| `event_log_sync_interval_minutes` | `0` | 定期一括イベントログ同期の間隔（分）。`0` で無効。 |
| `manager_health_sync_interval_minutes` | `0` | 定期一括 BMC ヘルス同期の間隔（分）。`0` で無効。 |
| `default_verify_ssl` | `False` | 新規 BMC Endpoint 作成時の SSL 検証デフォルト値。 |
| `service_account` | — | バックグラウンドジョブ用サービスアカウント名（netbox-secrets 使用時）。 |
| `service_private_key_path` | — | サービスアカウントの秘密鍵パス（netbox-secrets 使用時）。 |

各 `*_sync_interval_minutes` 設定は、0 より大きい値を設定すると **全** BMC Endpoint 分の
定期同期ジョブが有効になります。この設定とは別に、各 Endpoint 詳細画面のカード
（Network / Sensors / Event Log / BMC Health）にも手動の「Sync」ボタンがあり、そのエンドポイント
1台分だけをオンデマンドで同期できます。

## 使い方

### インベントリ同期

1. NetBox の Device 画面から **BMC Endpoints** → **追加** をクリック
2. BMC アドレスと認証情報を入力して保存
3. Endpoint 詳細画面の **[Build Modules]** ボタンをクリック
4. コンポーネントプレビューを確認（新規 / 更新あり / 変更なし / 削除候補）
5. 同期するコンポーネントにチェックを入れて **[Apply Selected]** を実行

ModuleBay / ModuleType / Module が自動作成または更新されます。

### 電源操作

Endpoint 詳細画面の電源ボタングループから操作します：

| ボタン | 操作 |
|---|---|
| **On** | 電源 ON |
| **Off** | 強制電源 OFF（確認ダイアログあり） |
| **Soft** | ACPI グレースフルシャットダウン |
| **Cycle** | パワーサイクル（OFF → ON）（確認ダイアログあり） |
| **Reset** | 強制リセット（確認ダイアログあり） |
| **Identify On / Off** | シャーシの Identify ランプを点灯/消灯 |

電源状態は常にライブ取得（キャッシュしない）ため、電源操作直後の実際の状態を反映します。

### Network / Sensors / Event Log / BMC Health

それぞれ Endpoint 詳細画面に専用カードがあり、「Sync」ボタンで更新します：

| カード | Sync ボタン | 表示内容 |
|---|---|---|
| Network | Sync Network | BMC の全ネットワークインターフェース（IPv4/IPv6 アドレス、DHCP、VLAN、MAC、ホスト名/FQDN、DNSサーバー、リンク状態） |
| Sensors | Sync Sensors | 温度・Fan回転数・電圧・消費電力の実測値 |
| Event Log | Sync Event Log | 直近の System Event Log (SEL) エントリ |
| Sync Status → BMC Health | Sync Manager Health | BMC のヘルス状態 |

Sync ボタンを押すとバックグラウンドジョブがキューに入り、完了するとカードの「Last Sync」
タイムスタンプが更新され、テーブルに最新データが反映されます。BMC Firmware（Sync Status
カード内に表示）は滅多に変わらないため、専用の Sync ボタンではなく **Build Modules** 実行時
（Inventory スキャン）に更新されます。

### Module 命名規則

ベンダー固有の名前は統一フォーマットに正規化されます：

| Redfish 生値 | 正規化後 |
|---|---|
| `CPU.Socket.1` / `Processor 0` | `CPU 0` |
| `DIMM.A1` / `Memory 0` | `Memory 0` |
| `Disk.Bay.0` | `Drive 0` |
| `NIC.Slot.1`（PCIe） | `PCI 0` |

### カスタムフィールド

各 Module に以下のカスタムフィールドが自動設定されます：

| フィールド | 内容 |
|---|---|
| `bmc_redfish_path` | 取得元 Redfish URI |
| `bmc_firmware_version` | ファームウェアバージョン文字列 |

## 対応バージョン

| netbox-bmc | NetBox |
|---|---|
| 0.4.x | 4.5, 4.6 |

## ベンダー別注意事項

### Dell iDRAC

iDRAC 9（Redfish 1.x）を主なターゲットとしています。URI は ServiceRoot のリンクを辿って取得するためハードコードなし。ファームウェアのバリエーションは自動的に吸収されます。

### HPE iLO

iLO 5 / iLO 6 は HPE サブクラスドライバで対応しています。iLO 4（Redfish 1.0 準拠度が低い旧世代）は**未検証**のため動作しない可能性があります。

### Lenovo XCC

XCC2 / XCC3 に対応しています。古い XCC ファームウェアでは非標準のコレクション URI が使われる場合がありますが、リンク探索により多くのバリエーションを吸収します。

### Supermicro

汎用 Redfish ドライバを使用します。Supermicro の BMC ファームウェアはバージョンによって挙動が異なる場合があります。

### AMI (American Megatrends)

AMI Redfish Server（ServiceRoot の `Vendor: "AMI"` で検出）。PCIe デバイスが `Systems/PCIeDevices` ではなく `Chassis/PCIeDevices` 配下にあるため、AMI サブクラスドライバが自動的に対応します。CPU・Memory のインベントリはホスト電源 ON 時のみ取得できます。

### Intel AMT (Active Management Technology)

Intel AMT は vPro 対応 Intel CPU（第 6 世代以降）に内蔵される OOB 管理機能。WS-MAN（HTTPS ポート 16993 上の SOAP/XML）と HTTP Digest 認証で接続します。

自動検出: Redfish が応答しない場合、`detect_and_build()` がポート 16993 に WS-MAN `Identify` リクエストを送ります。AMT が応答すれば `IntelAmtDriver` を選択し、それも失敗した場合は IPMI にフォールバックします。

AMT を明示指定するには、`BMCEndpoint` の `protocol` を `"wsman"` に設定してください。

取得情報: CPU（CIM_Processor）、Memory（CIM_PhysicalMemory）、AMT ファームウェアバージョン（WS-MAN Identity）。Storage・PCIe は AMT WS-MAN では取得できません。

AMT がプロビジョニング済みで管理ポートがファイアウォールで遮断されていないことが前提です。AMT 5.x 以前は動作未検証です。

## 開発

```bash
# 開発依存関係のインストール
uv sync --extra dev

# テスト実行
uv run pytest
```

### 新ベンダーの追加

1. `netbox_bmc/drivers/redfish.py` に `RedfishDriver` のサブクラスを追加
2. `netbox_bmc/drivers/base.py` の `detect_and_build()` で ServiceRoot ベンダーキーに対応するディスパッチを登録
3. `tests/test_redfish_extensions.py` にユニットテストを追加

### 新プロトコルの追加

`netbox_bmc/drivers/base.py` の `BaseDriver` を実装し、`get_inventory()` から `InventoryResult` を返してください。

## 認証情報

BMC 認証情報は以下の順で解決されます：

1. **netbox-secrets**（優先） — `bmc-credentials` ロールの `Secret` が Device に紐付けられている場合。  
   `Secret.name` = BMC ユーザー名、`Secret.plaintext` = BMC パスワード（RSA 暗号化）。
2. **平文フォールバック** — netbox-secrets 未インストール、またはシークレット未設定時に `BMCEndpoint` の `username` / `password` フィールドを使用。

バックグラウンドジョブ（定期同期）では、`PLUGINS_CONFIG` に `service_account` と `service_private_key_path` を設定することで HTTP セッションなしで復号できます。

SecretRole/UserKey/サービスアカウントのセットアップ手順とセッションアンロックの流れは [docs/NETBOX_SECRETS.md](docs/NETBOX_SECRETS.md) を参照してください。

## 既知の制限

- REST API は `BMCEndpoint` の CRUD のみ。同期トリガーやセンサー/イベントログ/ネットワークの参照系は API 未提供
- マルチノードシャーシ（Systems が複数）未対応
- 定期一括 **Module** インベントリ同期（ScheduledInventorySyncJob）未実装（Network/Sensors/Event Log/BMC Health の定期同期は実装済み）
- KVM / SOL コンソールは旧プラグインから未移植
- Redfish 準拠度の低い古い BMC（HPE iLO 4 等）での動作未検証

## ライセンス

Apache License 2.0 — [LICENSE](LICENSE) 参照。
