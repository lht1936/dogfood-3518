"""REST API服务"""

from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Depends, Query, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from .database import get_db, SystemMetric, Server, settings
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


class ServerCreate(BaseModel):
    """创建服务器请求模型"""
    hostname: str = Field(..., description="服务器主机名（唯一标识）", min_length=1)
    name: Optional[str] = Field(None, description="服务器显示名称")
    ip_address: str = Field(..., description="服务器IP地址", min_length=1)
    port: int = Field(default=9100, description="Prometheus exporter端口", ge=1, le=65535)
    metrics_path: str = Field(default="/metrics", description="metrics端点路径", min_length=1)
    description: Optional[str] = Field(None, description="服务器描述")


class ServerUpdate(BaseModel):
    """更新服务器请求模型"""
    name: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    metrics_path: Optional[str] = None
    is_enabled: Optional[bool] = None
    description: Optional[str] = None


class ServerResponse(BaseModel):
    """服务器响应模型"""
    id: int
    hostname: str
    name: Optional[str]
    ip_address: str
    port: int
    metrics_path: str
    is_enabled: bool
    status: str
    last_seen: Optional[datetime]
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


@app.get("/")
def root():
    """根路径，返回API信息"""
    return {
        "service": "服务器运维监控平台",
        "version": __version__,
        "endpoints": {
            "指标查询": {
                "metrics": "/api/metrics",
                "average": "/api/metrics/average",
                "hosts": "/api/hosts"
            },
            "服务器管理": {
                "list_servers": "GET /api/servers",
                "create_server": "POST /api/servers",
                "get_server": "GET /api/servers/{id}",
                "update_server": "PUT /api/servers/{id}",
                "delete_server": "DELETE /api/servers/{id}",
                "enable_server": "PATCH /api/servers/{id}/enable",
                "disable_server": "PATCH /api/servers/{id}/disable"
            },
            "health": "/api/health",
            "docs": "/docs"
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


@app.post("/api/servers", response_model=ServerResponse, status_code=201)
def create_server(
    server: ServerCreate,
    db: Session = Depends(get_db)
):
    """
    添加新服务器到监控列表
    
    - **hostname**: 服务器主机名（唯一标识）
    - **ip_address**: 服务器IP地址
    - **port**: Prometheus exporter端口（默认9100）
    - **metrics_path**: metrics端点路径（默认/metrics）
    - **name**: 服务器显示名称（可选）
    - **description**: 服务器描述（可选）
    
    注意：被监控的服务器需要运行 Prometheus node_exporter
    """
    existing_server = db.query(Server).filter(Server.hostname == server.hostname).first()
    if existing_server:
        raise HTTPException(
            status_code=400,
            detail=f"主机名 '{server.hostname}' 已存在"
        )
    
    new_server = Server(
        hostname=server.hostname,
        name=server.name,
        ip_address=server.ip_address,
        port=server.port,
        metrics_path=server.metrics_path,
        is_enabled=True,
        status="unknown",
        description=server.description
    )
    
    db.add(new_server)
    db.commit()
    db.refresh(new_server)
    
    return new_server


@app.get("/api/servers", response_model=List[ServerResponse])
def list_servers(
    is_enabled: Optional[bool] = Query(None, description="按启用状态过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    db: Session = Depends(get_db)
):
    """
    获取所有被监控的服务器列表
    
    - **is_enabled**: 按启用状态过滤（可选）
    - **status**: 按状态过滤（可选：online/offline/unknown）
    """
    query = db.query(Server)
    
    if is_enabled is not None:
        query = query.filter(Server.is_enabled == is_enabled)
    if status:
        query = query.filter(Server.status == status)
    
    servers = query.order_by(desc(Server.created_at)).all()
    return servers


@app.get("/api/servers/{server_id}", response_model=ServerResponse)
def get_server(
    server_id: int = Path(..., description="服务器ID"),
    db: Session = Depends(get_db)
):
    """
    获取指定服务器的详情
    
    - **server_id**: 服务器ID
    """
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=404,
            detail=f"服务器 ID {server_id} 不存在"
        )
    return server


@app.put("/api/servers/{server_id}", response_model=ServerResponse)
def update_server(
    server_id: int = Path(..., description="服务器ID"),
    server_update: ServerUpdate = None,
    db: Session = Depends(get_db)
):
    """
    更新服务器信息
    
    - **server_id**: 服务器ID
    - 支持更新：name、ip_address、port、metrics_path、is_enabled、description
    """
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=404,
            detail=f"服务器 ID {server_id} 不存在"
        )
    
    update_data = server_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(server, key, value)
    
    db.commit()
    db.refresh(server)
    
    return server


@app.delete("/api/servers/{server_id}", status_code=204)
def delete_server(
    server_id: int = Path(..., description="服务器ID"),
    db: Session = Depends(get_db)
):
    """
    从监控列表中删除服务器
    
    - **server_id**: 服务器ID
    """
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=404,
            detail=f"服务器 ID {server_id} 不存在"
        )
    
    db.delete(server)
    db.commit()
    
    return None


@app.patch("/api/servers/{server_id}/enable", response_model=ServerResponse)
def enable_server(
    server_id: int = Path(..., description="服务器ID"),
    db: Session = Depends(get_db)
):
    """
    启用服务器监控
    
    - **server_id**: 服务器ID
    """
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=404,
            detail=f"服务器 ID {server_id} 不存在"
        )
    
    server.is_enabled = True
    db.commit()
    db.refresh(server)
    
    return server


@app.patch("/api/servers/{server_id}/disable", response_model=ServerResponse)
def disable_server(
    server_id: int = Path(..., description="服务器ID"),
    db: Session = Depends(get_db)
):
    """
    禁用服务器监控
    
    - **server_id**: 服务器ID
    """
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=404,
            detail=f"服务器 ID {server_id} 不存在"
        )
    
    server.is_enabled = False
    db.commit()
    db.refresh(server)
    
    return server
