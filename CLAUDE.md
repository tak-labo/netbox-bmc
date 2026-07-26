# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

`netbox_bmc` は NetBox 4.5+ のプラグイン。Redfish / WS-MAN(Intel AMT) / IPMI を統一インターフェースで
扱い、BMC からのインベントリ同期・電源操作・ネットワーク/センサー/イベントログ/ヘルス監視を提供する。
旧 `netbox-ipmi-plugin` の後継で、Redfish を第一級でサポートするのが設計上の差分。
KVM/SOL コンソールは旧プラグインから意図的に移植していない(価値がないと判断し、一度追加した
クイックランチボタンも撤去済み)。

## 開発コマンド

```bash
# 開発依存関係のインストール
uv sync --extra dev

# lint / format / test (Makefile 経由でも可: make lint / make fmt / make test)
uv run ruff check .
uv run ruff format .
uv run pytest

# 単一ファイル
uv run pytest tests/test_normalizer.py

# 単一テスト
uv run pytest -k test_firmware_kind_uses_firmware_label
```

テストは Django 不要で実行できる。`tests/conftest.py` が `dcim` / `netbox` モジュールを
`MagicMock` で差し替えているため、NetBox インストールなしに単体テストが通る。逆に言うと
`jobs.py`・`views.py`・`models.py` など Django に依存するコードはこの pytest スイートでは
import すら通らない(`from django.utils import timezone` 等で ModuleNotFoundError になる)。
これらの層は netbox-docker 上での手動検証で担保する設計。

### NetBox 環境での動作確認

このリポジトリ単体には実行環境がない。動作確認は `../netbox-docker/` から実施する：

```bash
docker compose exec netbox pip install -e /path/to/netbox-bmc
docker compose exec netbox python manage.py migrate
docker compose restart netbox netbox-worker
```

マイグレーションを新規追加した際は `manage.py makemigrations netbox_bmc --check --dry-run` で
差分がないか検証する(`manage.py makemigrations` 本体は `DEVELOPER=True` 前提の netbox-docker
コンテナでは実行できないことがあるため、hand-write + check の運用)。

### i18n (英語/日本語)

UI 文字列は全て `gettext_lazy as _`(Python)/ `{% trans %}`(テンプレート)でラップし、
`netbox_bmc/locale/ja/LC_MESSAGES/django.po` に対応する msgid/msgstr を追加する。
`Meta.verbose_name` など Django が naive に `+ "s"` で複数形を作る箇所は **翻訳しない**
(翻訳すると "BMCエンドポイントs" のような壊れた複数形になる)。
`msgfmt`/`xgettext` が入っていない環境では `.po` から `.mo` を手動でコンパイルするスクリプトが
必要になる(バイナリの `.mo` は素直な `git merge` ができないため、コンフリクト時は必ず
マージ後の `.po` から再コンパイルする)。

## アーキテクチャ

レイヤ分離が中心の設計思想。Driver → 中間表現 (`inventory.py`) → Normalizer / Job → NetBox。

```
drivers/base.py       # BaseDriver 抽象 + detect_and_build()
                      # ── auto: /redfish/v1 を probe → 応答なければ (ポート未指定時) AMT(16993) を probe → IPMI にフォールバック
                      # ── ServiceRoot の Vendor / Oem からベンダーサブクラスへディスパッチ
drivers/redfish.py    # 汎用ドライバ + Dell/HPE/Lenovo サブクラス
                      # ── URI ハードコード禁止。ServiceRoot のリンクを辿る
                      # ── PSU/Fan/センサーは Chassis リンク経由 (Thermal/Power)、PCIe は PCIeDevices コレクション
                      # ── ネットワーク設定は Managers/{id}/EthernetInterfaces (Systems 側の EthernetInterfaces はホストOSのNIC)
                      # ── Identify LED は Chassis.LocationIndicatorActive を PATCH (ETag/If-Match 対応、旧スキーマの IndicatorLED にフォールバック)
drivers/ipmi.py       # pyghmi ベースのフォールバック
drivers/amt.py        # Intel AMT (vPro) 向け WS-MAN ドライバ。追加ライブラリなし (requests + stdlib xml)
inventory.py          # InventoryResult / Component / BmcNetworkInterface / ManagerInfo /
                      # SensorReading / SelEntry など、ドライバの戻り値の中間表現
                      # ── ドライバはここまでしか返さない。NetBox を一切知らない
normalizer.py         # Component → NormalizedComponent (KIND N 形式に正規化)
                      # ── ベンダー固有の名前を "CPU 0", "Memory 1" 等に統一
module_sync.py        # 中間表現 → NetBox の Module / ModuleBay / ModuleType への差分同期
                      # ── compute_diff: 既存 bmc-synced Module との差分計算
                      # ── entry_to_dict: DiffEntry → UI セッション用 dict に変換
                      # ── apply_module_sync: session_entries を NetBox に適用
                      # ── apply_firmware_to_device: firmware dict を Device CF に書き込み
                      # ── 'bmc-synced' タグ付きアイテムのみ管理。手動追加には触れない
credentials.py        # netbox-secrets 優先 → 平文フォールバックの順で認証情報解決
                      # ── SecretRole "bmc-credentials" の Secret を Device に紐付けて RSA 復号
                      # ── netbox-secrets 未インストール or シークレット未設定時は平文フィールド
jobs.py               # 各種バックグラウンドジョブ (下記「同期の2系統」参照)
models.py             # BMCEndpoint (Device と 1:1)。get_driver(request=...) がドライバ生成の唯一の入口
views.py / urls.py    # 詳細ページの各カードは「即時実行系」と「Sync ボタン→ジョブ→DB反映系」に分かれる
template_content.py   # DeviceBMCPanel (PluginTemplateExtension) — Device 詳細画面に
                      # BMC情報パネル(right_page)と「View BMC Endpoint」ボタン(buttons)を注入。
                      # BMCEndpoint が存在しない Device には何も表示しない
api/                  # REST API (NetBoxModelViewSet + NetBoxRouter)。BMCEndpoint の CRUD のみ
```

### 同期の2系統(重要な設計判断)

BMC から取得するデータは「変化頻度」によって扱いが分かれている:

- **即時実行・都度ライブ取得(DB非保存)**: Power Status。電源操作の直後に古い状態を
  見せると意味がないため、ページ表示のたびに `PowerStatusView` が直接取得する。
- **DB永続化 + バックグラウンドジョブ**: Network / Sensors / Event Log / BMC Health / BMC Firmware。
  ページはボタン押下時に対応する `*SyncJob`(`NetworkSyncJob` / `SensorsSyncJob` /
  `EventLogSyncJob` / `ManagerHealthSyncJob`)を `enqueue` するだけで、実際の取得・DB書き込みは
  非同期ジョブ側(`jobs.py` の `_sync_*` ヘルパー)が行う。各カードは
  `BMCEndpoint.network_interfaces` / `sensors` / `event_log` / `manager_health` と対応する
  `*_last_sync` を表示するだけ。
  - BMC Firmware だけは例外的に、専用ジョブを持たず **Inventory スキャン
    (`BuildModulesView` = 「Build Modules」ボタン)** の一部として `detected_firmware_version`
    に保存される。理由: ファームウェアバージョンは滅多に変わらないため、専用の定期ジョブを
    持つコストに見合わない。一方 BMC Health は変化しうるため独立した `ManagerHealthSyncJob`
    を持つ。
  - 各 `Scheduled*SyncJob`(全エンドポイント一括)は `PLUGINS_CONFIG` の
    `*_sync_interval_minutes` が 0 より大きい場合のみ `ready()` で登録される
    (`_enqueue_scheduled_job` が同名 Job の pending/scheduled/running 重複登録を防ぐ)。
  - Sync Status カードの「Inventory Last Sync」/「Inventory Scan Status」(`last_sync` /
    `last_sync_status`)は上記とは別物で、`BuildModulesView` の Module インベントリスキャンの
    結果を指す。名前が紛らわしいため意図的に「Inventory」を冠して区別している。

重要な不変条件：

- **ドライバ層は NetBox を知らない**。出力は `inventory.py` の中間表現のみ。
- **同期の差分管理は `bmc-synced` タグで分離**。手動 Module を上書き／削除しない。
- **Redfish のパスは ServiceRoot 経由のリンク探索**で得る。iDRAC / iLO / XCC / Supermicro の
  パス差分はコード変更なしで吸収する設計なので、ベンダー固有 URI を直書きしない。
- **認証情報は `BMCEndpoint.get_driver(request=...)` 経由で取得**する。
  `request` がない (バックグラウンドジョブ等) ケースはサービスアカウント秘密鍵 → 平文の順。

## プラグイン設定

`PLUGINS_CONFIG["netbox_bmc"]` で受ける主要キー：

| キー | 用途 |
|---|---|
| `sync_interval_minutes` | >0 で全 BMCEndpoint の定期一括 Module 同期を有効化 (0 で無効、実体は未実装スタブ) |
| `network_sync_interval_minutes` | >0 で全 BMCEndpoint の定期ネットワーク設定同期を有効化 |
| `sensors_sync_interval_minutes` | >0 で全 BMCEndpoint の定期センサー同期を有効化 |
| `event_log_sync_interval_minutes` | >0 で全 BMCEndpoint の定期イベントログ同期を有効化 |
| `manager_health_sync_interval_minutes` | >0 で全 BMCEndpoint の定期ヘルス同期を有効化 |
| `network_sync_enabled` / `sensors_sync_enabled` / `event_log_sync_enabled` / `manager_health_sync_enabled` | デフォルト `True`。`False` にするとその同期種別をプラグイン全体で無効化するマスタースイッチ (各 `BMCEndpoint` の同名チェックボックスより優先) |
| `default_verify_ssl` | エンドポイント作成時の SSL 検証デフォルト |
| `service_account` / `service_private_key_path` | netbox-secrets 利用時のバックグラウンドジョブ用 |

## 既知の制限

- マルチノードシャーシ (Systems が複数) 未対応
- 定期一括 **Module** 同期 (`ScheduledInventorySyncJob`) は未実装のスタブ
  (Network/Sensors/Event Log/Manager Health の定期同期は実装済み)
- KVM / SOL コンソールは旧プラグインから意図的に未移植
- Redfish 準拠度の低い古い BMC (HPE iLO 4 等) での動作未検証
- REST API は `BMCEndpoint` の CRUD のみ (同期トリガーやセンサー/イベントログの参照系は未提供)
