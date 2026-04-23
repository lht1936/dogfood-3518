"""数据采集调度器"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .collector import SystemMetricsCollector
from .database import settings

logger = logging.getLogger(__name__)


class MetricsScheduler:
    """指标采集调度器"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.collector = SystemMetricsCollector()
        self.is_running = False

    def _collect_job(self):
        """定时采集任务"""
        try:
            metrics = self.collector.collect_and_save()
            logger.info(
                f"指标采集成功 - 主机: {metrics['hostname']}, "
                f"CPU: {metrics['cpu_usage']:.1f}%, "
                f"内存: {metrics['memory_usage']:.1f}%"
            )
        except Exception as e:
            logger.error(f"指标采集失败: {str(e)}")

    def start(self, interval_seconds: int = None):
        """启动调度器
        
        Args:
            interval_seconds: 采集间隔（秒），默认为配置文件中的设置
        """
        if self.is_running:
            logger.warning("调度器已经在运行中")
            return

        interval = interval_seconds or settings.COLLECT_INTERVAL

        self.scheduler.add_job(
            self._collect_job,
            trigger=IntervalTrigger(seconds=interval),
            id='metrics_collection',
            name='系统指标采集',
            replace_existing=True
        )

        self.scheduler.start()
        self.is_running = True
        logger.info(f"调度器已启动，采集间隔: {interval}秒")
        
        self._collect_job()

    def stop(self):
        """停止调度器"""
        if not self.is_running:
            logger.warning("调度器已经停止")
            return

        self.scheduler.shutdown(wait=False)
        self.is_running = False
        logger.info("调度器已停止")

    def collect_now(self):
        """立即执行一次采集"""
        logger.info("执行立即采集")
        self._collect_job()
