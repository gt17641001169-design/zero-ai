"""MCP 配置文件管理 - ~/.zeroai/mcp_config.json

管理 MCP 服务器的连接配置，支持：
1. 加载/保存配置文件
2. 添加/删除/列出服务器配置
3. 支持 stdio 和 SSE 两种传输方式
4. 环境变量注入（启动子进程时传递）

配置文件格式：
{
  "mcpServers": {
    "server_name": {
      "transport": "stdio",          // 或 "sse"
      "command": "python",            // stdio 模式：启动命令
      "args": ["-m", "mcp_server"],   // stdio 模式：命令参数
      "env": {},                       // stdio 模式：环境变量
      "cwd": "",                        // stdio 模式：工作目录
      "url": "http://...",             // SSE 模式：服务器 URL
      "headers": {},                   // SSE 模式：HTTP 头
      "enabled": true,                 // 是否启用
      "description": "服务器描述"
    }
  }
}
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# 配置文件路径：~/.zeroai/mcp_config.json
MCP_CONFIG_DIR = Path.home() / ".zeroai"
MCP_CONFIG_FILE = MCP_CONFIG_DIR / "mcp_config.json"


@dataclass
class MCPServerConfig:
    """单个 MCP 服务器配置"""
    name: str
    transport: str = "stdio"  # "stdio" | "sse"
    # stdio 模式
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    # SSE 模式
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    # 通用
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # 不保存 name 到字典内（name 作为外层 key）
        d.pop("name", None)
        # 清理空值，保持配置简洁
        if not self.env:
            d.pop("env")
        if not self.cwd:
            d.pop("cwd")
        if not self.headers:
            d.pop("headers")
        if not self.args:
            d.pop("args")
        if not self.description:
            d.pop("description")
        return d

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MCPServerConfig":
        """从字典构造配置"""
        return cls(
            name=name,
            transport=data.get("transport", "stdio"),
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            cwd=data.get("cwd", ""),
            url=data.get("url", ""),
            headers=data.get("headers", {}),
            enabled=data.get("enabled", True),
            description=data.get("description", ""),
        )

    def validate(self) -> Optional[str]:
        """校验配置，返回错误信息（None 表示通过）"""
        if self.transport not in ("stdio", "sse"):
            return f"不支持的传输方式: {self.transport}（仅支持 stdio/sse）"
        if self.transport == "stdio" and not self.command:
            return "stdio 模式必须指定 command"
        if self.transport == "sse" and not self.url:
            return "sse 模式必须指定 url"
        return None

    def build_env(self) -> Dict[str, str]:
        """构造子进程环境变量（继承当前进程 + 自定义）"""
        env = dict(os.environ)
        env.update(self.env)
        return env


class MCPConfig:
    """MCP 配置管理器"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or MCP_CONFIG_FILE
        self._servers: Dict[str, MCPServerConfig] = {}
        self.load()

    def load(self) -> None:
        """从文件加载配置"""
        self._servers = {}
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            if not isinstance(servers, dict):
                return
            for name, cfg in servers.items():
                if not isinstance(cfg, dict):
                    continue
                self._servers[name] = MCPServerConfig.from_dict(name, cfg)
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> bool:
        """保存配置到文件"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "mcpServers": {
                    name: cfg.to_dict()
                    for name, cfg in self._servers.items()
                }
            }
            self.config_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError:
            return False

    def list_servers(self, only_enabled: bool = False) -> List[MCPServerConfig]:
        """列出所有服务器配置"""
        servers = list(self._servers.values())
        if only_enabled:
            servers = [s for s in servers if s.enabled]
        return servers

    def get_server(self, name: str) -> Optional[MCPServerConfig]:
        """获取单个服务器配置"""
        return self._servers.get(name)

    def add_server(self, config: MCPServerConfig) -> bool:
        """添加或更新服务器配置

        Returns:
            True 添加成功，False 配置无效
        """
        err = config.validate()
        if err:
            return False
        self._servers[config.name] = config
        return self.save()

    def remove_server(self, name: str) -> bool:
        """删除服务器配置"""
        if name not in self._servers:
            return False
        del self._servers[name]
        return self.save()

    def enable_server(self, name: str) -> bool:
        """启用服务器"""
        if name not in self._servers:
            return False
        self._servers[name].enabled = True
        return self.save()

    def disable_server(self, name: str) -> bool:
        """禁用服务器"""
        if name not in self._servers:
            return False
        self._servers[name].enabled = False
        return self.save()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "mcpServers": {
                name: cfg.to_dict() for name, cfg in self._servers.items()
            }
        }


# ============================================================================
# 全局单例
# ============================================================================
_config_instance: Optional[MCPConfig] = None


def get_mcp_config() -> MCPConfig:
    """获取全局 MCP 配置实例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = MCPConfig()
    return _config_instance


def reload_mcp_config() -> MCPConfig:
    """重新加载 MCP 配置"""
    global _config_instance
    _config_instance = MCPConfig()
    return _config_instance


__all__ = [
    "MCP_CONFIG_DIR",
    "MCP_CONFIG_FILE",
    "MCPServerConfig",
    "MCPConfig",
    "get_mcp_config",
    "reload_mcp_config",
]
