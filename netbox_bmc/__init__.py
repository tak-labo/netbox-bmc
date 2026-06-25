from netbox.plugins import PluginConfig

__version__ = "0.4.0"
__author__ = "tak-labo"
__email__ = ""


class NetBoxBMCConfig(PluginConfig):
    name = "netbox_bmc"
    verbose_name = "NetBox BMC (IPMI/Redfish)"
    description = "Unified out-of-band management: Redfish & IPMI inventory sync, power control, console access"
    version = __version__
    author = __author__
    author_email = __email__
    base_url = "bmc"
    min_version = "4.5"
    max_version = "4.6.99"
    default_settings = {
        # 定期一括同期の間隔 (分)。0 で無効。
        "sync_interval_minutes": 0,
        "default_verify_ssl": False,
        # netbox-secrets バックグラウンドジョブ用サービスアカウント設定
        # (netbox-secrets 使用時のみ必要)
        # "service_account": "bmc-sync",
        # "service_private_key_path": "/opt/netbox/bmc-sync.pem",
    }

    def ready(self):
        super().ready()
        from . import jobs  # noqa: F401

        interval = (getattr(self, "settings", None) or {}).get("sync_interval_minutes") or 0
        if interval:
            self._enqueue_scheduled_sync(interval)

    @staticmethod
    def _enqueue_scheduled_sync(interval_minutes: int) -> None:
        """
        ScheduledInventorySyncJob の定期ジョブを登録する。

        ready() は workers / web プロセスの起動ごとに呼ばれるため、
        既に pending / scheduled / running の同名ジョブがあればスキップして
        冪等にする。初回マイグレーション前など Job テーブル未作成の場合は黙って抜ける。
        """
        import logging
        from django.db import DatabaseError

        from .jobs import ScheduledInventorySyncJob

        logger = logging.getLogger("netbox_bmc")

        try:
            from core.models import Job
            from django.utils import timezone
            from datetime import timedelta

            active = Job.objects.filter(
                name=ScheduledInventorySyncJob.Meta.name,
                status__in=("pending", "scheduled", "running"),
            ).exists()
            if active:
                return

            ScheduledInventorySyncJob.enqueue(
                instance=None,
                schedule_at=timezone.now() + timedelta(minutes=interval_minutes),
                interval=interval_minutes,
            )
        except DatabaseError:
            # マイグレーション前: Job テーブルが存在しない
            pass
        except Exception as e:
            logger.warning("Failed to schedule recurring inventory sync: %s", e)


config = NetBoxBMCConfig
