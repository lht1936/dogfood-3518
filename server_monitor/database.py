"""数据库配置和模型"""

from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Index, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""
    DATABASE_URL: str = "sqlite:///./monitor.db"
    HOSTNAME: str = "localhost"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    COLLECT_INTERVAL: int = 60  # 采集间隔，单位秒

    class Config:
        env_file = ".env"


settings = Settings()

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Server(Base):
    """被监控服务器模型"""
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True, comment="服务器显示名称")
    ip_address = Column(String, nullable=False, comment="服务器IP地址")
    port = Column(Integer, default=9100, comment="Prometheus exporter端口（默认9100）")
    metrics_path = Column(String, default="/metrics", comment="metrics端点路径")
    is_enabled = Column(Boolean, default=True, comment="是否启用监控")
    status = Column(String, default="unknown", comment="服务器状态: online/offline/unknown")
    last_seen = Column(DateTime, nullable=True, comment="最后一次在线时间")
    description = Column(String, nullable=True, comment="服务器描述")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "hostname": self.hostname,
            "name": self.name,
            "ip_address": self.ip_address,
            "port": self.port,
            "metrics_path": self.metrics_path,
            "is_enabled": self.is_enabled,
            "status": self.status,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class SystemMetric(Base):
    """系统指标数据模型"""
    __tablename__ = "system_metrics"

    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime, index=True, nullable=False)
    
    cpu_usage = Column(Float, nullable=False, comment="CPU使用率(百分比)")
    
    memory_total = Column(Float, nullable=False, comment="总内存(字节)")
    memory_available = Column(Float, nullable=False, comment="可用内存(字节)")
    memory_used = Column(Float, nullable=False, comment="已用内存(字节)")
    memory_usage = Column(Float, nullable=False, comment="内存使用率(百分比)")
    
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_hostname_timestamp', hostname, timestamp),
    )


def init_db():
    """初始化数据库"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
