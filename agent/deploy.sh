#!/bin/bash
#
# 服务器监控Agent一键部署脚本
# 用户只需要在被监控服务器上执行此脚本即可完成全部部署
#
# 使用方法:
#   curl -s http://<中央服务器>:8000/deploy.sh | bash -s -- <服务器名称>
#
# 例如:
#   curl -s http://192.168.1.100:8000/deploy.sh | bash -s -- "Web服务器01"
#

set -e

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 日志函数
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 获取脚本来源的中央服务器地址
SCRIPT_SOURCE="${HTTP_SCHEME}://${HTTP_HOST}"
if [ -z "$HTTP_HOST" ]; then
    # 如果无法从环境变量获取，尝试从命令行获取
    if [ -n "$1" ] && [[ "$1" == http* ]]; then
        SCRIPT_SOURCE="$1"
        shift
    else
        error "无法确定中央服务器地址"
        info "请使用以下格式执行:"
        info "  curl -s http://<中央服务器>:8000/deploy.sh | bash -s -- <服务器名称>"
        exit 1
    fi
fi

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
    PYTHON_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
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
IP_ADDRESS=$(hostname -I | awk '{print $1}')

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
