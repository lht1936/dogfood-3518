"""数据库配置和模型"""

from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Index
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
