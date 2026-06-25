# netbox-bmc-plugin

IPMI/Redfish 統合のアウトオブバンド管理プラグイン。
netbox-ipmi-plugin の後継として、マルチベンダー対応の Redfish を第一級でサポートする。

## 機能 (v0.3)

- **Module ビルダー**: BMC から検出したハードウェアを NetBox の Module として登録
  - Redfish スキャン → コンポーネント一覧をプレビュー表示
  - 個別チェックボックスで登録するコンポーネントを選択
  - 新規 / 更新あり / 変更なし / 削除候補 をカラーバッジで表示
  - ModuleBay が存在しない場合は自動作成（プレビューで事前通知）
  - FRU 交換後のシリアル変更を検出して差分更新
  - `bmc-synced` タグ付き Module のみ管理。手動登録 Module には触れない
  - NIC の MAC は既存 Interface との突合のみ（Module 対象外）
- **収集コンポーネント**:
  - CPU / Memory / Drive / PSU / Fan / Firmware / PCI デバイス
  - PSU・Fan は Chassis リンク経由、PCIe は PCIeDevices コレクション経由
- **プロトコル自動検出**: `/redfish/v1` を probe → 失敗時 IPMI フォールバック
- **ベンダー自動検出**: ServiceRoot の Vendor / Oem キーから判別し
  必要に応じて Dell / HPE / Lenovo ドライバへディスパッチ
- **電源操作**: on / off / soft / cycle / reset（両プロトコル対応）

## アーキテクチャ

```
drivers/
  base.py        # BaseDriver + detect_and_build（プロトコル自動判別）
  redfish.py     # リンク探索ベースの汎用ドライバ + ベンダーサブクラス
  ipmi.py        # pyghmi ベースのフォールバック
inventory.py     # 正規化中間表現（InventoryResult / Component）
normalizer.py    # Component → NormalizedComponent（"CPU 0" 等に正規化）
module_sync.py   # 中間表現 → Module / ModuleBay / ModuleType の差分同期
jobs.py          # ScheduledInventorySyncJob（定期一括同期、現在は stub）
```

ポイント: Redfish の URI はハードコードせず ServiceRoot からリンクを辿るため、
iDRAC / iLO / XCC / Supermicro のパス差分はコード変更なしで吸収される。

## インストール

```bash
pip install ./netbox-bmc-plugin
```

`configuration.py`:

```python
PLUGINS = ["netbox_bmc"]
PLUGINS_CONFIG = {
    "netbox_bmc": {
        "sync_interval_minutes": 0,  # >0 で全デバイス定期同期（未実装）
        "default_verify_ssl": False,
    },
}
```

```bash
python manage.py makemigrations netbox_bmc
python manage.py migrate
```

## 使い方

1. NetBox の Device に **BMC Endpoint** を追加（アドレス・認証情報を設定）
2. Endpoint 詳細画面の **[Build Modules]** ボタンをクリック
3. BMC スキャンが実行され、検出コンポーネントのプレビューが表示される
4. 登録したいコンポーネントにチェックを入れて **[Apply Selected]** を実行
5. ModuleBay / ModuleType / Module が自動作成される

### Module 名の命名規則

ベンダー固有の名前（`CPU.Socket.1`、`Processor 0` 等）は自動的に正規化される：

| Redfish 生値 | 正規化後 |
|---|---|
| `CPU.Socket.1` / `Processor 0` | `CPU 0` |
| `DIMM.A1` / `Memory 0` | `Memory 0` |
| `Disk.Bay.0` | `Drive 0` |
| `NIC.Slot.1` (PCIe) | `PCI 0` |

### カスタムフィールド

Module に以下のカスタムフィールドが自動設定される：

| フィールド | 内容 |
|---|---|
| `bmc_redfish_path` | 取得元 Redfish パス |
| `bmc_firmware_version` | ファームウェアバージョン |

## テスト

```bash
uv sync --extra dev
uv run pytest
```

## 既知の制限 / TODO

- [ ] **認証情報が平文保存** — netbox-secrets または HashiCorp Vault 統合へ移行すること
- [ ] REST API（api/serializers, viewsets）未実装
- [ ] マルチノードシャーシ（Systems が複数）未対応
- [ ] 定期一括 Module 同期（ScheduledInventorySyncJob）未実装
- [ ] KVM / SOL コンソールは旧プラグインから未移植
- [ ] HPE iLO4 など Redfish 準拠度の低い古い BMC での検証
