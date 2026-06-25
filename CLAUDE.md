# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

`netbox_bmc` は NetBox 4.0+ のプラグイン。Redfish と IPMI を統一インターフェースで扱い、
BMC からのインベントリ同期 / 電源操作 / (将来的に) コンソールを提供する。
旧 `netbox-ipmi-plugin` の後継で、Redfish を第一級でサポートするのが設計上の差分。

## セットアップ / 開発フロー

このリポジトリ単体には実行環境がない。動作確認は親 `netbox-docker/` から実施する：

```bash
# 親ディレクトリの netbox-docker 環境に installしてリロード
cd ../netbox-docker
# configuration/plugins.py の PLUGINS に "netbox_bmc" を入れる
docker compose exec netbox pip install -e /path/to/netbox-bmc-plugin
docker compose exec netbox python manage.py makemigrations netbox_bmc
docker compose exec netbox python manage.py migrate
docker compose restart netbox netbox-worker
```

`pyproject.toml` の dependencies は `requests` と `pyghmi` のみ。テストランナーや lint 設定は未定義。

## アーキテクチャ

レイヤ分離が中心の設計思想。Driver → 中間表現 → Normalizer → Sync の 4 段。

```
drivers/base.py       # BaseDriver 抽象 + detect_and_build()
                      # ── /redfish/v1 を probe → 失敗時 IPMI フォールバック
                      # ── ServiceRoot の Vendor / Oem からベンダーサブクラスへディスパッチ
drivers/redfish.py    # 汎用ドライバ + Dell/HPE/Lenovo サブクラス
                      # ── URI ハードコード禁止。ServiceRoot のリンクを辿る
                      # ── PSU/Fan は Chassis リンク経由、PCIe は PCIeDevices コレクション
drivers/ipmi.py       # pyghmi ベースのフォールバック
inventory.py          # InventoryResult / Component の正規化中間表現
                      # ── ドライバはここまでしか返さない
normalizer.py         # Component → NormalizedComponent (KIND N 形式に正規化)
                      # ── ベンダー固有の名前を "CPU 0", "Memory 1" 等に統一
module_sync.py        # 中間表現 → NetBox の Module / ModuleBay / ModuleType への差分同期
                      # ── compute_diff: 既存 bmc-synced Module との差分計算
                      # ── apply_module_sync: session_entries を NetBox に適用
                      # ── 'bmc-synced' タグ付きアイテムのみ管理。手動追加には触れない
credentials.py        # netbox-secrets 優先 → 平文フォールバックの順で認証情報解決
jobs.py               # ScheduledInventorySyncJob (一括同期は未実装、stub)
models.py             # BMCEndpoint (Device と 1:1)
```

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
| `sync_interval_minutes` | >0 で全 BMCEndpoint の定期一括同期を有効化 (0 で無効) |
| `default_verify_ssl` | エンドポイント作成時の SSL 検証デフォルト |
| `service_account` / `service_private_key_path` | netbox-secrets 利用時のバックグラウンドジョブ用 |

`ready()` 内で interval>0 のとき `ScheduledInventorySyncJob.enqueue_once()` を呼ぶ。
プラグイン再ロード時の二重登録を避けるため `enqueue_once` 側で冪等にする必要がある。

## 既知の制限 (README 参照)

- 認証情報の平文保存 → netbox-secrets / Vault 統合へ移行予定
- REST API (serializers / viewsets) 未実装
- マルチノードシャーシ (Systems が複数) 未対応
- KVM / SOL コンソールは旧プラグインから未移植
