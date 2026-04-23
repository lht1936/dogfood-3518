"""REST API服务"""

from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Depends, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from .database import get_db, SystemMetric, settings
from . import __version__


app = FastAPI(
    title="服务器运维监控平台API",
    description="提供服务器CPU和内存指标查询服务",
    version=__version__
)


class MetricResponse(BaseModel):
    """指标响应模型"""
    id: int
    hostname: str
    timestamp: datetime
    cpu_usage: float
    memory_usage: float
    memory_total: float
    memory_used: float
    
    class Config:
        from_attributes = True


class AverageMetricsResponse(BaseModel):
    """平均指标响应模型"""
    hostname: str
    start_time: datetime
    end_time: datetime
    avg_cpu_usage: float
    avg_memory_usage: float
    data_points: int
    first_sample_time: Optional[datetime] = None
    last_sample_time: Optional[datetime] = None


class HostListResponse(BaseModel):
    """主机列表响应模型"""
    hostname: str
    last_seen: datetime
    total_metrics: int


@app.get("/")
def root():
    """根路径，返回API信息"""
    return {
        "service": "服务器运维监控平台",
        "version": __version__,
        "endpoints": {
            "metrics": "/api/metrics",
            "average": "/api/metrics/average",
            "hosts": "/api/hosts"
        }
    }


@app.get("/api/metrics", response_model=List[MetricResponse])
def get_metrics(
    hostname: str = Query(..., description="主机名"),
    start_time: Optional[datetime] = Query(None, description="开始时间（ISO格式）"),
    end_time: Optional[datetime] = Query(None, description="结束时间（ISO格式）"),
    limit: int = Query(100, ge=1, le=1000, description="返回记录数限制"),
    db: Session = Depends(get_db)
):
    """
    获取指定主机的指标数据
    
    - **hostname**: 主机名（必需）
    - **start_time**: 开始时间（可选）
    - **end_time**: 结束时间（可选）
    - **limit**: 返回记录数限制（默认100）
    """
    query = db.query(SystemMetric).filter(SystemMetric.hostname == hostname)
    
    if start_time:
        query = query.filter(SystemMetric.timestamp >= start_time)
    if end_time:
        query = query.filter(SystemMetric.timestamp <= end_time)
    
    metrics = query.order_by(desc(SystemMetric.timestamp)).limit(limit).all()
    
    return metrics


@app.get("/api/metrics/average", response_model=AverageMetricsResponse)
def get_average_metrics(
    hostname: str = Query(..., description="主机名"),
    start_time: Optional[datetime] = Query(None, description="开始时间（ISO格式）"),
    end_time: Optional[datetime] = Query(None, description="结束时间（ISO格式）"),
    db: Session = Depends(get_db)
):
    """
    获取指定主机某段时间的平均CPU使用率和内存使用率
    
    - **hostname**: 主机名（必需）
    - **start_time**: 开始时间（可选，默认最近1小时）
    - **end_time**: 结束时间（可选，默认当前时间）
    
    返回结果包含：
    - 平均CPU使用率
    - 平均内存使用率
    - 数据点数量
    - 实际采样时间范围
    """
    if end_time is None:
        end_time = datetime.utcnow()
    
    if start_time is None:
        start_time = end_time - timedelta(hours=1)
    
    query = db.query(
        func.avg(SystemMetric.cpu_usage).label('avg_cpu'),
        func.avg(SystemMetric.memory_usage).label('avg_memory'),
        func.count(SystemMetric.id).label('count'),
        func.min(SystemMetric.timestamp).label('first_time'),
        func.max(SystemMetric.timestamp).label('last_time')
    ).filter(
        SystemMetric.hostname == hostname,
        SystemMetric.timestamp >= start_time,
        SystemMetric.timestamp <= end_time
    )
    
    result = query.first()
    
    if result.count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"主机 {hostname} 在指定时间范围内没有找到指标数据"
        )
    
    return AverageMetricsResponse(
        hostname=hostname,
        start_time=start_time,
        end_time=end_time,
        avg_cpu_usage=round(result.avg_cpu, 2) if result.avg_cpu else 0.0,
        avg_memory_usage=round(result.avg_memory, 2) if result.avg_memory else 0.0,
        data_points=result.count,
        first_sample_time=result.first_time,
        last_sample_time=result.last_time
    )


@app.get("/api/hosts", response_model=List[HostListResponse])
def get_hosts(
    db: Session = Depends(get_db)
):
    """
    获取所有已监控的主机列表
    
    返回每个主机的：
    - 主机名
    - 最后一次上报时间
    - 总指标数据条数
    """
    query = db.query(
        SystemMetric.hostname,
        func.max(SystemMetric.timestamp).label('last_seen'),
        func.count(SystemMetric.id).label('total_metrics')
    ).group_by(SystemMetric.hostname).order_by(desc(func.max(SystemMetric.timestamp)))
    
    hosts = query.all()
    
    return [
        HostListResponse(
            hostname=host.hostname,
            last_seen=host.last_seen,
            total_metrics=host.total_metrics
        )
        for host in hosts
    ]


@app.get("/api/health")
def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }
