"""
バックグラウンドジョブ。

InventorySyncJob: InventoryItem 同期 (削除済み — Module sync は views の
  BuildModulesApplyView で行うインタラクティブフローに移行)

ScheduledInventorySyncJob: 全エンドポイントの定期一括 Module 同期 (未実装)
  bulk module sync は今後の実装タスクで追加予定。
"""
import logging

from netbox.jobs import JobRunner

from .models import BMCEndpoint

logger = logging.getLogger("netbox_bmc.jobs")


class ScheduledInventorySyncJob(JobRunner):
    """全エンドポイントの定期 Module 同期 (bulk module sync は未実装)。"""

    class Meta:
        name = "BMC Inventory Sync (all devices)"

    def run(self, *args, **kwargs):
        self.job.data = {
            "message": "Scheduled bulk module sync not yet implemented. "
                       "Use the 'Build Modules' button per endpoint."
        }
        logger.info("ScheduledInventorySyncJob: bulk module sync not yet implemented.")
