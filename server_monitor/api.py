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


class AgentRegisterRequest(BaseModel):
    """Agent注册请求"""
    hostname: str
    ip_address: str
    name: Optional[str] = None
    agent_version: str = "1.0.0"
    description: Optional[str] = None


class AgentRegisterResponse(BaseModel):
    """Agent注册响应"""
    server_id: int
    hostname: str
    status: str
    message: str


class AgentMetricsPush(BaseModel):
    """Agent推送指标请求"""
    hostname: str
    timestamp: datetime
    cpu_usage: float
    memory_total: float
    memory_available: float
    memory_used: float
    memory_usage: float
    
    load1: Optional[float] = None
    load5: Optional[float] = None
    load15: Optional[float] = None


class AgentMetricsResponse(BaseModel):
    """Agent推送指标响应"""
    status: str
    message: str
    received_at: datetime


@app.post("/api/agent/register", response_model=AgentRegisterResponse, status_code=201)
def agent_register(
    request: AgentRegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Agent自动注册接口（Push模式）
    
    Agent启动时自动调用此接口注册服务器。
    如果主机名已存在，则更新服务器信息；否则创建新服务器。
    
    - **hostname**: 服务器主机名（唯一标识）
    - **ip_address**: 服务器IP地址
    - **name**: 服务器显示名称（可选）
    - **agent_version**: Agent版本
    - **description**: 服务器描述（可选）
    """
    existing_server = db.query(Server).filter(Server.hostname == request.hostname).first()
    
    if existing_server:
        existing_server.ip_address = request.ip_address
        existing_server.status = "online"
        existing_server.last_seen = datetime.utcnow()
        existing_server.is_enabled = True
        if request.name:
            existing_server.name = request.name
        if request.description:
            existing_server.description = request.description
        
        db.commit()
        db.refresh(existing_server)
        
        return AgentRegisterResponse(
            server_id=existing_server.id,
            hostname=existing_server.hostname,
            status="updated",
            message="服务器已更新"
        )
    
    new_server = Server(
        hostname=request.hostname,
        name=request.name or request.hostname,
        ip_address=request.ip_address,
        port=0,
        metrics_path="/agent-push",
        is_enabled=True,
        status="online",
        last_seen=datetime.utcnow(),
        description=request.description or f"Agent注册 - {request.agent_version}"
    )
    
    db.add(new_server)
    db.commit()
    db.refresh(new_server)
    
    return AgentRegisterResponse(
        server_id=new_server.id,
        hostname=new_server.hostname,
        status="registered",
        message="服务器注册成功"
    )


@app.post("/api/agent/metrics", response_model=AgentMetricsResponse)
def agent_push_metrics(
    request: AgentMetricsPush,
    db: Session = Depends(get_db)
):
    """
    Agent推送指标接口（Push模式）
    
    Agent每分钟调用此接口推送系统指标。
    
    - **hostname**: 服务器主机名
    - **timestamp**: 指标采集时间
    - **cpu_usage**: CPU使用率（百分比）
    - **memory_total**: 总内存（字节）
    - **memory_available**: 可用内存（字节）
    - **memory_used**: 已用内存（字节）
    - **memory_usage**: 内存使用率（百分比）
    - **load1/5/15**: 系统负载（可选）
    """
    server = db.query(Server).filter(Server.hostname == request.hostname).first()
    
    if not server:
        raise HTTPException(
            status_code=404,
            detail=f"服务器 {request.hostname} 未注册，请先调用 /api/agent/register 注册"
        )
    
    metric_record = SystemMetric(
        hostname=request.hostname,
        timestamp=request.timestamp,
        cpu_usage=request.cpu_usage,
        memory_total=request.memory_total,
        memory_available=request.memory_available,
        memory_used=request.memory_used,
        memory_usage=request.memory_usage
    )
    db.add(metric_record)
    
    server.status = "online"
    server.last_seen = datetime.utcnow()
    db.commit()
    
    return AgentMetricsResponse(
        status="success",
        message="指标已接收",
        received_at=datetime.utcnow()
    )


@app.post("/api/agent/heartbeat")
def agent_heartbeat(
    hostname: str = Query(..., description="服务器主机名"),
    db: Session = Depends(get_db)
):
    """
    Agent心跳接口
    
    Agent定期调用此接口更新在线状态。
    
    - **hostname**: 服务器主机名
    """
    server = db.query(Server).filter(Server.hostname == hostname).first()
    
    if not server:
        raise HTTPException(
            status_code=404,
            detail=f"服务器 {hostname} 未注册"
        )
    
    server.last_seen = datetime.utcnow()
    server.status = "online"
    db.commit()
    
    return {
        "status": "ok",
        "message": "心跳已接收",
        "timestamp": datetime.utcnow()
    }


from fastapi import Request
from fastapi.responses import PlainTextResponse, FileResponse
from pathlib import Path

AGENT_DIR = Path(__file__).parent.parent / "agent"


def generate_deploy_script(server_url: str) -> str:
    """
    动态生成部署脚本，嵌入中央服务器地址
    
    Args:
        server_url: 中央服务器地址 (如: http://192.168.1.100:8000)
    
    Returns:
        生成的部署脚本内容
    """
    return f'''#!/bin/bash
#
# 服务器监控Agent一键部署脚本
# 中央服务器: {server_url}
#
# 使用方法:
#   curl -s {server_url}/deploy.sh | bash -s -- "服务器名称"
#

set -e

# 颜色输出
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
RED='\\033[0;31m'
NC='\\033[0m'

# 日志函数
info() {{
    echo -e "${{GREEN}}[INFO]${{NC}} $1"
}}

warn() {{
    echo -e "${{YELLOW}}[WARN]${{NC}} $1"
}}

error() {{
    echo -e "${{RED}}[ERROR]${{NC}} $1"
}}

# 中央服务器地址（已嵌入）
SCRIPT_SOURCE="{server_url}"

# 服务器名称
SERVER_NAME="$1"
if [ -z "$SERVER_NAME" ]; then
    SERVER_NAME=$(hostname)
fi

info "=========================================="
info "  服务器监控Agent一键部署脚本"
info "=========================================="
info "中央服务器: $SCRIPT_SOURCE"
info "服务器名称: $SERVER_NAME"
info ""

# 检查Python
info "1. 检查Python环境..."
if command -v python3 &> /dev/null; then
    PYTHON=python3
    info "  已找到 Python3: $($PYTHON --version)"
elif command -v python &> /dev/null; then
    PYTHON=python
    PYTHON_VERSION=$($PYTHON --version 2>&1 | awk '{{print $2}}')
    if [[ $PYTHON_VERSION == 3* ]]; then
        info "  已找到 Python3: $PYTHON_VERSION"
    else
        error "需要 Python3，当前版本: $PYTHON_VERSION"
        exit 1
    fi
else
    error "未找到 Python，请先安装 Python3"
    info "  Ubuntu/Debian: sudo apt install python3 python3-pip"
    info "  CentOS/RHEL: sudo yum install python3 python3-pip"
    exit 1
fi

# 检查pip
info "2. 检查pip..."
if command -v pip3 &> /dev/null; then
    PIP=pip3
elif command -v pip &> /dev/null; then
    PIP=pip
else
    error "未找到 pip，请先安装"
    exit 1
fi
info "  已找到 pip"

# 安装psutil
info "3. 安装依赖包 (psutil, requests)..."
$PIP install psutil requests -q
info "  依赖安装完成"

# 下载Agent脚本
info "4. 下载Agent脚本..."
AGENT_DIR="/opt/monitor-agent"
sudo mkdir -p $AGENT_DIR

AGENT_URL="$SCRIPT_SOURCE/agent/agent.py"
info "  从 $AGENT_URL 下载..."

if command -v curl &> /dev/null; then
    sudo curl -s -o "$AGENT_DIR/agent.py" "$AGENT_URL"
elif command -v wget &> /dev/null; then
    sudo wget -q -O "$AGENT_DIR/agent.py" "$AGENT_URL"
else
    error "需要 curl 或 wget"
    exit 1
fi

sudo chmod +x "$AGENT_DIR/agent.py"
info "  Agent脚本已保存到: $AGENT_DIR/agent.py"

# 安装Systemd服务
info "5. 安装Systemd服务..."

HOSTNAME=$(hostname)
IP_ADDRESS=$(hostname -I | awk '{{print $1}}')

SERVICE_FILE="/etc/systemd/system/monitor-agent.service"

# 创建服务文件
sudo tee $SERVICE_FILE > /dev/null << EOF
[Unit]
Description=服务器监控Agent
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON $AGENT_DIR/agent.py --server $SCRIPT_SOURCE --hostname $HOSTNAME --name "$SERVER_NAME"
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
EOF

info "  服务文件已创建: $SERVICE_FILE"

# 重载并启动服务
info "6. 启动服务..."
sudo systemctl daemon-reload
sudo systemctl enable monitor-agent
sudo systemctl start monitor-agent

# 等待服务启动
sleep 2

# 检查服务状态
if systemctl is-active --quiet monitor-agent; then
    info "  服务启动成功"
else
    warn "  服务可能未正常启动，请检查日志"
fi

info ""
info "=========================================="
info "  部署完成！"
info "=========================================="
info ""
info "服务管理命令:"
info "  查看状态:  sudo systemctl status monitor-agent"
info "  查看日志:  sudo journalctl -u monitor-agent -f"
info "  重启服务:  sudo systemctl restart monitor-agent"
info "  停止服务:  sudo systemctl stop monitor-agent"
info ""
info "配置文件: /etc/monitor-agent/config.json"
info "Agent脚本: $AGENT_DIR/agent.py"
info ""
info "中央服务器: $SCRIPT_SOURCE"
info "本机主机名: $HOSTNAME"
info "本机IP: $IP_ADDRESS"
info ""
'''


@app.get("/deploy.sh", response_class=PlainTextResponse)
def get_deploy_script(request: Request):
    """
    提供一键部署脚本下载
    
    脚本会动态嵌入中央服务器地址，用户只需执行：
    curl -s http://<中央服务器>:8000/deploy.sh | bash -s -- "服务器名称"
    
    例如:
    curl -s http://192.168.1.100:8000/deploy.sh | bash -s -- "Web服务器01"
    """
    server_url = str(request.base_url).rstrip('/')
    
    deploy_script = AGENT_DIR / "deploy.sh"
    
    if not deploy_script.exists():
        script_content = generate_deploy_script(server_url)
    else:
        script_content = generate_deploy_script(server_url)
    
    return PlainTextResponse(
        content=script_content,
        media_type="text/x-shellscript"
    )


@app.get("/agent/agent.py")
def get_agent_script():
    """
    提供Agent脚本下载
    """
    agent_script = AGENT_DIR / "agent.py"
    
    if not agent_script.exists():
        raise HTTPException(
            status_code=404,
            detail="Agent脚本不存在"
        )
    
    return FileResponse(
        path=str(agent_script),
        media_type="text/x-python",
        filename="agent.py"
    )
