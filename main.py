"""服务器运维监控平台主程序入口"""

import logging
import signal
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from server_monitor.database import init_db, settings
from server_monitor.scheduler import MetricsScheduler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

scheduler = MetricsScheduler()


def signal_handler(sig, frame):
    """处理终止信号"""
    logger.info("收到终止信号，正在停止服务...")
    scheduler.stop()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    from server_monitor.api import app as api_app
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用生命周期管理"""
        logger.info("正在初始化数据库...")
        init_db()
        
        logger.info("正在启动指标采集调度器...")
        scheduler.start()
        
        logger.info("=" * 50)
        logger.info("服务器运维监控平台已启动")
        logger.info(f"API服务地址: http://{settings.API_HOST}:{settings.API_PORT}")
        logger.info(f"API文档地址: http://{settings.API_HOST}:{settings.API_PORT}/docs")
        logger.info(f"采集间隔: {settings.COLLECT_INTERVAL}秒")
        logger.info("=" * 50)
        
        yield
        
        logger.info("正在关闭指标采集调度器...")
        scheduler.stop()
        logger.info("服务器运维监控平台已停止")
    
    api_app.router.lifespan_context = lifespan
    return api_app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False
    )
