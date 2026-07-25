"""
バックグラウンドジョブ。

InventorySyncJob: InventoryItem 同期 (削除済み — Module sync は views の
  BuildModulesApplyView で行うインタラクティブフローに移行)

ScheduledInventorySyncJob: 全エンドポイントの定期一括 Module 同期 (未実装)
  bulk module sync は今後の実装タスクで追加予定。

NetworkSyncJob / ScheduledNetworkSyncJob: BMC 自身のネットワーク設定を取得し
  BMCEndpoint.network_interfaces / network_last_sync に保存する。
  get_driver(request=None) を使うため、netbox-secrets 利用時は
  service_account / service_private_key_path の設定が必要
  (credentials.py の request なし経路と同じ)。

SensorsSyncJob / ScheduledSensorsSyncJob: センサーテレメトリを取得し
  BMCEndpoint.sensors / sensors_last_sync に保存する。

EventLogSyncJob / ScheduledEventLogSyncJob: System Event Log を取得し
  BMCEndpoint.event_log / event_log_last_sync に保存する。

ManagerHealthSyncJob / ScheduledManagerHealthSyncJob: BMC自身のヘルス状態を取得し
  BMCEndpoint.manager_health / manager_health_last_sync に保存する。
  firmware_version は BuildModulesView の Inventory スキャンで
  detected_firmware_version に保存される (滅多に変わらないため専用ジョブなし)。
"""
import logging
from dataclasses import asdict

from django.utils import timezone
from netbox.jobs import JobRunner

logger = logging.getLogger("netbox_bmc.jobs")

EVENT_LOG_SYNC_LIMIT = 50


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


def _sync_network_config(endpoint, logger_=logger) -> Exception | None:
    """1 エンドポイント分のネットワーク設定を取得して DB に保存する。

    成功時は None、失敗時は捕捉した例外を返す (呼び出し元で件数集計や
    RuntimeError への連鎖ができるように)。1エンドポイントの失敗が一括
    ジョブ全体を止めないよう、例外はここで吸収する。
    """
    try:
        with endpoint.get_driver() as driver:
            ifaces = driver.get_network_config()
    except Exception as e:
        logger_.warning("Network sync failed for %s: %s", endpoint, e)
        return e

    endpoint.network_interfaces = [asdict(i) for i in ifaces]
    endpoint.network_last_sync = timezone.now()
    endpoint.save(update_fields=["network_interfaces", "network_last_sync"])
    return None


class NetworkSyncJob(JobRunner):
    """1 エンドポイントの Sync Network ボタンから起動される。"""

    class Meta:
        name = "BMC Network Sync"

    def run(self, *args, **kwargs):
        endpoint = self.job.object
        if endpoint is None:
            self.logger.error("NetworkSyncJob requires a BMCEndpoint instance")
            return
        error = _sync_network_config(endpoint, logger_=self.logger)
        if error is not None:
            raise RuntimeError(f"Network sync failed for {endpoint}: {error}") from error


class ScheduledNetworkSyncJob(JobRunner):
    """全エンドポイントの定期ネットワーク設定同期。"""

    class Meta:
        name = "BMC Network Sync (all devices)"

    def run(self, *args, **kwargs):
        from .models import BMCEndpoint

        endpoints = BMCEndpoint.objects.all()
        succeeded = sum(_sync_network_config(e, logger_=self.logger) is None for e in endpoints)
        self.job.data = {"message": f"Synced {succeeded}/{len(endpoints)} endpoint(s)."}


def _sync_sensors(endpoint, logger_=logger) -> Exception | None:
    """1 エンドポイント分のセンサーテレメトリを取得して DB に保存する。

    成功時は None、失敗時は捕捉した例外を返す。
    """
    try:
        with endpoint.get_driver() as driver:
            readings = driver.get_sensors()
    except Exception as e:
        logger_.warning("Sensors sync failed for %s: %s", endpoint, e)
        return e

    endpoint.sensors = [asdict(r) for r in readings]
    endpoint.sensors_last_sync = timezone.now()
    endpoint.save(update_fields=["sensors", "sensors_last_sync"])
    return None


class SensorsSyncJob(JobRunner):
    """1 エンドポイントの Sync Sensors ボタンから起動される。"""

    class Meta:
        name = "BMC Sensors Sync"

    def run(self, *args, **kwargs):
        endpoint = self.job.object
        if endpoint is None:
            self.logger.error("SensorsSyncJob requires a BMCEndpoint instance")
            return
        error = _sync_sensors(endpoint, logger_=self.logger)
        if error is not None:
            raise RuntimeError(f"Sensors sync failed for {endpoint}: {error}") from error


class ScheduledSensorsSyncJob(JobRunner):
    """全エンドポイントの定期センサー同期。"""

    class Meta:
        name = "BMC Sensors Sync (all devices)"

    def run(self, *args, **kwargs):
        from .models import BMCEndpoint

        endpoints = BMCEndpoint.objects.all()
        succeeded = sum(_sync_sensors(e, logger_=self.logger) is None for e in endpoints)
        self.job.data = {"message": f"Synced {succeeded}/{len(endpoints)} endpoint(s)."}


def _sync_event_log(endpoint, logger_=logger) -> Exception | None:
    """1 エンドポイント分の System Event Log を取得して DB に保存する。

    成功時は None、失敗時は捕捉した例外を返す。
    """
    try:
        with endpoint.get_driver() as driver:
            entries = driver.get_event_log(limit=EVENT_LOG_SYNC_LIMIT)
    except Exception as e:
        logger_.warning("Event log sync failed for %s: %s", endpoint, e)
        return e

    endpoint.event_log = [asdict(e) for e in entries]
    endpoint.event_log_last_sync = timezone.now()
    endpoint.save(update_fields=["event_log", "event_log_last_sync"])
    return None


class EventLogSyncJob(JobRunner):
    """1 エンドポイントの Sync Event Log ボタンから起動される。"""

    class Meta:
        name = "BMC Event Log Sync"

    def run(self, *args, **kwargs):
        endpoint = self.job.object
        if endpoint is None:
            self.logger.error("EventLogSyncJob requires a BMCEndpoint instance")
            return
        error = _sync_event_log(endpoint, logger_=self.logger)
        if error is not None:
            raise RuntimeError(f"Event log sync failed for {endpoint}: {error}") from error


class ScheduledEventLogSyncJob(JobRunner):
    """全エンドポイントの定期イベントログ同期。"""

    class Meta:
        name = "BMC Event Log Sync (all devices)"

    def run(self, *args, **kwargs):
        from .models import BMCEndpoint

        endpoints = BMCEndpoint.objects.all()
        succeeded = sum(_sync_event_log(e, logger_=self.logger) is None for e in endpoints)
        self.job.data = {"message": f"Synced {succeeded}/{len(endpoints)} endpoint(s)."}


def _sync_manager_health(endpoint, logger_=logger) -> Exception | None:
    """1 エンドポイント分の BMC ヘルス状態を取得して DB に保存する。

    成功時は None、失敗時は捕捉した例外を返す。
    firmware_version は滅多に変わらないため、ここでは扱わない
    (Inventory スキャン (BuildModulesView) 側で detected_firmware_version に保存される)。
    """
    try:
        with endpoint.get_driver() as driver:
            info = driver.get_manager_info()
    except Exception as e:
        logger_.warning("Manager health sync failed for %s: %s", endpoint, e)
        return e

    endpoint.manager_health = info.health
    endpoint.manager_health_last_sync = timezone.now()
    endpoint.save(update_fields=["manager_health", "manager_health_last_sync"])
    return None


class ManagerHealthSyncJob(JobRunner):
    """1 エンドポイントの Sync Manager Health ボタンから起動される。"""

    class Meta:
        name = "BMC Manager Health Sync"

    def run(self, *args, **kwargs):
        endpoint = self.job.object
        if endpoint is None:
            self.logger.error("ManagerHealthSyncJob requires a BMCEndpoint instance")
            return
        error = _sync_manager_health(endpoint, logger_=self.logger)
        if error is not None:
            raise RuntimeError(f"Manager health sync failed for {endpoint}: {error}") from error


class ScheduledManagerHealthSyncJob(JobRunner):
    """全エンドポイントの定期 Manager Health 同期。"""

    class Meta:
        name = "BMC Manager Health Sync (all devices)"

    def run(self, *args, **kwargs):
        from .models import BMCEndpoint

        endpoints = BMCEndpoint.objects.all()
        succeeded = sum(_sync_manager_health(e, logger_=self.logger) is None for e in endpoints)
        self.job.data = {"message": f"Synced {succeeded}/{len(endpoints)} endpoint(s)."}
