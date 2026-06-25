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
| Redfish | Dell iDRAC, HPE iLO, Lenovo XCC, Supermicro, Generic |
| IPMI | IPMI 対応 BMC 全般（フォールバック） |

プロトコルは自動検出します。まず `/redfish/v1` を probe し、失敗した場合 IPMI にフォールバックします。

## テスト済みハードウェア

| メーカー | モデルシリーズ | BMC | プロトコル | 状態 |
|---|---|---|---|---|
| Dell | PowerEdge | iDRAC 9 | Redfish | 動作見込み |
| HPE | ProLiant | iLO 5 | Redfish | 動作見込み |
| HPE | ProLiant | iLO 6 | Redfish | 動作見込み |
| Lenovo | ThinkSystem | XCC2 / XCC3 | Redfish | 動作見込み |
| Supermicro | X12 / X13 | BMC | Redfish | 動作見込み |
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
- **ベンダー自動検出**: ServiceRoot の `Vendor` / `Oem` キーから Dell / HPE / Lenovo サブクラスドライバへディスパッチ
- **電源操作**: on / off / soft / cycle / reset（両プロトコル対応）

## インストール

### 標準環境（非 Docker）

```bash
pip install netbox-bmc
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

マイグレーション実行：

```bash
python manage.py migrate
```

### Docker 環境（netbox-docker）

`docker-compose.override.yml` にボリュームマウントを追加：

```yaml
services:
  netbox: &netbox
    volumes:
      - ./netbox-bmc:/opt/netbox-bmc
```

editable インストール後、コンテナを再起動：

```bash
docker compose exec netbox pip install -e /opt/netbox-bmc
docker compose exec netbox python manage.py migrate
docker compose restart netbox netbox-worker
```

## 設定

`configuration.py` の `PLUGINS_CONFIG["netbox_bmc"]` で設定します：

| キー | デフォルト | 説明 |
|---|---|---|
| `sync_interval_minutes` | `0` | 定期一括同期の間隔（分）。`0` で無効。 |
| `default_verify_ssl` | `False` | 新規 BMC Endpoint 作成時の SSL 検証デフォルト値。 |
| `service_account` | — | バックグラウンドジョブ用サービスアカウント名（netbox-secrets 使用時）。 |
| `service_private_key_path` | — | サービスアカウントの秘密鍵パス（netbox-secrets 使用時）。 |

## 使い方

1. NetBox の Device 画面から **BMC Endpoints** → **追加** をクリック
2. BMC アドレスと認証情報を入力して保存
3. Endpoint 詳細画面の **[Build Modules]** ボタンをクリック
4. コンポーネントプレビューを確認（新規 / 更新あり / 変更なし / 削除候補）
5. 同期するコンポーネントにチェックを入れて **[Apply Selected]** を実行

ModuleBay / ModuleType / Module が自動作成または更新されます。

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

## 既知の制限

- REST API（serializers / viewsets）未実装
- マルチノードシャーシ（Systems が複数）未対応
- 定期一括同期（ScheduledInventorySyncJob）未実装
- KVM / SOL コンソールは旧プラグインから未移植
- Redfish 準拠度の低い古い BMC（HPE iLO 4 等）での動作未検証

## ライセンス

Apache License 2.0 — [LICENSE](LICENSE) 参照。
