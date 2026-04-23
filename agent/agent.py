#!/usr/bin/env python3
"""
服务器监控Agent - 自动采集系统指标并推送到中央监控服务器

功能：
1. 自动采集CPU、内存等系统指标
2. 自动注册到中央监控服务器
3. 每分钟推送指标到中央服务器
4. 支持Systemd服务管理
"""

import argparse
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("monitor-agent")


class MonitorAgent:
    """监控Agent"""

    AGENT_VERSION = "1.0.0"
    DEFAULT_INTERVAL = 60
    CONFIG_DIR = Path("/etc/monitor-agent")
    CONFIG_FILE = CONFIG_DIR / "config.json"
    LOG_FILE = Path("/var/log/monitor-agent.log")

    def __init__(
        self,
        server_url: str,
        hostname: Optional[str] = None,
        name: Optional[str] = None,
        interval: int = DEFAULT_INTERVAL
    ):
        self.server_url = server_url.rstrip('/')
        self.hostname = hostname or socket.gethostname()
        self.name = name or self.hostname
        self.interval = interval
        self.ip_address = self._get_local_ip()
        self.server_id: Optional[int] = None
        self.is_registered = False
        self.is_running = False

        self.register_url = f"{self.server_url}/api/agent/register"
        self.metrics_url = f"{self.server_url}/api/agent/metrics"
        self.heartbeat_url = f"{self.server_url}/api/agent/heartbeat"

    def _get_local_ip(self) -> str:
        """获取本机IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _get_system_metrics(self) -> Dict[str, Any]:
        """采集系统指标"""
        try:
            import psutil
        except ImportError:
            logger.error("psutil 未安装，请运行: pip install psutil")
            raise RuntimeError("psutil 模块未安装")

        cpu_percent = psutil.cpu_percent(interval=1)
        
        memory = psutil.virtual_memory()
        memory_total = memory.total
        memory_available = memory.available
        memory_used = memory.used
        memory_percent = memory.percent

        load1, load5, load15 = 0.0, 0.0, 0.0
        try:
            load1, load5, load15 = psutil.getloadavg()
        except Exception:
            pass

        return {
            "hostname": self.hostname,
            "timestamp": datetime.utcnow(),
            "cpu_usage": cpu_percent,
            "memory_total": float(memory_total),
            "memory_available": float(memory_available),
            "memory_used": float(memory_used),
            "memory_usage": memory_percent,
            "load1": load1,
            "load5": load5,
            "load15": load15
        }

    def register(self) -> bool:
        """注册到中央服务器"""
        try:
            payload = {
                "hostname": self.hostname,
                "ip_address": self.ip_address,
                "name": self.name,
                "agent_version": self.AGENT_VERSION,
                "description": f"Monitor Agent on {platform.system()} {platform.release()}"
            }

            logger.info(f"正在注册到中央服务器: {self.register_url}")
            logger.info(f"注册信息: {json.dumps(payload, indent=2, default=str)}")

            response = requests.post(
                self.register_url,
                json=payload,
                timeout=10
            )

            if response.status_code in (200, 201):
                result = response.json()
                self.server_id = result.get("server_id")
                self.is_registered = True
                logger.info(f"注册成功! 服务器ID: {self.server_id}, 状态: {result.get('status')}")
                return True
            else:
                logger.error(f"注册失败，状态码: {response.status_code}, 响应: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"注册时发生网络错误: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"注册时发生错误: {str(e)}")
            return False

    def push_metrics(self) -> bool:
        """推送指标到中央服务器"""
        if not self.is_registered:
            logger.warning("未注册，先尝试注册...")
            if not self.register():
                return False

        try:
            metrics = self._get_system_metrics()
            metrics["timestamp"] = metrics["timestamp"].isoformat()

            logger.debug(f"推送指标: CPU={metrics['cpu_usage']:.1f}%, 内存={metrics['memory_usage']:.1f}%")

            response = requests.post(
                self.metrics_url,
                json=metrics,
                timeout=10
            )

            if response.status_code == 200:
                logger.debug(f"指标推送成功")
                return True
            else:
                logger.error(f"指标推送失败，状态码: {response.status_code}, 响应: {response.text}")
                if response.status_code == 404:
                    logger.warning("服务器未注册，尝试重新注册...")
                    self.is_registered = False
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"推送指标时发生网络错误: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"推送指标时发生错误: {str(e)}")
            return False

    def send_heartbeat(self) -> bool:
        """发送心跳"""
        try:
            response = requests.post(
                self.heartbeat_url,
                params={"hostname": self.hostname},
                timeout=5
            )
            return response.status_code == 200
        except Exception:
            return False

    def start(self):
        """启动Agent"""
        logger.info("=" * 50)
        logger.info(f"服务器监控Agent v{self.AGENT_VERSION} 启动")
        logger.info(f"主机名: {self.hostname}")
        logger.info(f"IP地址: {self.ip_address}")
        logger.info(f"中央服务器: {self.server_url}")
        logger.info(f"采集间隔: {self.interval}秒")
        logger.info("=" * 50)

        if not self.register():
            logger.warning("首次注册失败，将在下次采集时重试")

        self.is_running = True
        consecutive_failures = 0
        max_consecutive_failures = 5

        while self.is_running:
            try:
                if not self.is_registered:
                    if self.register():
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        if consecutive_failures >= max_consecutive_failures:
                            logger.error(f"连续 {max_consecutive_failures} 次注册失败，等待...")
                            time.sleep(self.interval)
                            continue

                if self.push_metrics():
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.warning(f"指标推送失败，连续失败次数: {consecutive_failures}")

                for _ in range(self.interval):
                    if not self.is_running:
                        break
                    time.sleep(1)

            except KeyboardInterrupt:
                logger.info("收到中断信号，正在停止...")
                self.stop()
                break
            except Exception as e:
                logger.error(f"主循环发生错误: {str(e)}")
                time.sleep(self.interval)

    def stop(self):
        """停止Agent"""
        logger.info("Agent正在停止...")
        self.is_running = False


def load_config() -> Optional[Dict[str, Any]]:
    """从配置文件加载配置"""
    if MonitorAgent.CONFIG_FILE.exists():
        try:
            with open(MonitorAgent.CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
    return None


def save_config(config: Dict[str, Any]):
    """保存配置到文件"""
    try:
        MonitorAgent.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(MonitorAgent.CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"配置已保存到: {MonitorAgent.CONFIG_FILE}")
    except Exception as e:
        logger.error(f"保存配置失败: {str(e)}")


def install_systemd_service(
    server_url: str,
    hostname: Optional[str] = None,
    name: Optional[str] = None,
    interval: int = 60
) -> bool:
    """安装为Systemd服务"""
    if platform.system() != 'Linux':
        logger.error("Systemd服务仅支持Linux系统")
        return False

    script_path = Path(__file__).absolute()
    
    exec_start = f"{sys.executable} {script_path}"
    exec_start += f" --server {server_url}"
    if hostname:
        exec_start += f" --hostname {hostname}"
    if name:
        exec_start += f" --name {name}"
    exec_start += f" --interval {interval}"

    service_content = f"""[Unit]
Description=服务器监控Agent
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
"""

    service_file = Path("/etc/systemd/system/monitor-agent.service")
    
    try:
        service_file.write_text(service_content)
        logger.info(f"服务文件已创建: {service_file}")

        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "monitor-agent"], check=True)
        subprocess.run(["systemctl", "start", "monitor-agent"], check=True)

        logger.info("Systemd服务已安装并启动")
        logger.info("管理命令:")
        logger.info("  启动: systemctl start monitor-agent")
        logger.info("  停止: systemctl stop monitor-agent")
        logger.info("  状态: systemctl status monitor-agent")
        logger.info("  日志: journalctl -u monitor-agent -f")

        return True

    except Exception as e:
        logger.error(f"安装Systemd服务失败: {str(e)}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="服务器监控Agent - 自动采集系统指标并推送到中央监控服务器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 前台运行
  python agent.py --server http://192.168.1.100:8000
  
  # 指定主机名
  python agent.py --server http://192.168.1.100:8000 --hostname web-server-01
  
  # 安装为Systemd服务
  python agent.py --server http://192.168.1.100:8000 --install
        """
    )

    parser.add_argument(
        "--server", "-s",
        type=str,
        help="中央监控服务器URL (如: http://192.168.1.100:8000)"
    )
    parser.add_argument(
        "--hostname",
        type=str,
        default=None,
        help="自定义主机名 (默认使用系统主机名)"
    )
    parser.add_argument(
        "--name", "-n",
        type=str,
        default=None,
        help="服务器显示名称"
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=60,
        help="采集间隔（秒），默认60秒"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="配置文件路径"
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="安装为Systemd服务（仅Linux）"
    )
    parser.add_argument(
        "--register-only",
        action="store_true",
        help="仅注册，不启动采集循环"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="测试模式：只采集一次指标并打印"
    )

    args = parser.parse_args()

    config = None
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)
        else:
            logger.error(f"配置文件不存在: {args.config}")
            sys.exit(1)
    else:
        config = load_config()

    server_url = args.server or (config.get("server_url") if config else None)
    if not server_url:
        logger.error("未指定中央服务器URL，请使用 --server 参数或配置文件")
        parser.print_help()
        sys.exit(1)

    hostname = args.hostname or (config.get("hostname") if config else None)
    name = args.name or (config.get("name") if config else None)
    interval = args.interval or (config.get("interval", 60) if config else 60)

    agent = MonitorAgent(
        server_url=server_url,
        hostname=hostname,
        name=name,
        interval=interval
    )

    if args.register_only:
        logger.info("仅注册模式")
        success = agent.register()
        if success:
            config_data = {
                "server_url": server_url,
                "hostname": agent.hostname,
                "name": agent.name,
                "interval": interval
            }
            save_config(config_data)
        sys.exit(0 if success else 1)

    if args.test:
        logger.info("测试模式 - 采集一次指标")
        metrics = agent._get_system_metrics()
        metrics["timestamp"] = metrics["timestamp"].isoformat()
        print(json.dumps(metrics, indent=2, default=str))
        sys.exit(0)

    if args.install:
        logger.info("安装Systemd服务模式")
        success = install_systemd_service(
            server_url=server_url,
            hostname=hostname,
            name=name,
            interval=interval
        )
        if success:
            config_data = {
                "server_url": server_url,
                "hostname": hostname or socket.gethostname(),
                "name": name,
                "interval": interval
            }
            save_config(config_data)
        sys.exit(0 if success else 1)

    try:
        agent.start()
    except KeyboardInterrupt:
        logger.info("用户中断，退出")
        sys.exit(0)


if __name__ == "__main__":
    main()
