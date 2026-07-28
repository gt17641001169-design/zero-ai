"""MCP 服务器预设 - 常用官方 MCP 服务器的配置模板

提供主流 MCP 服务器的预置配置，用户无需手动编写命令参数：
- filesystem：文件系统访问（@modelcontextprotocol/server-filesystem）
- git：Git 仓库操作（@modelcontextprotocol/server-git）
- sqlite：SQLite 数据库查询（@modelcontextprotocol/server-sqlite）
- fetch：网页抓取（@modelcontextprotocol/server-fetch）
- memory：持久化记忆（@modelcontextprotocol/server-memory）
- brave-search：Brave 搜索（需要 API Key）
- sequential-thinking：顺序思考（@modelcontextprotocol/server-sequential-thinking）
- time：时间日期（@modelcontextprotocol/server-time）

使用方式：
    from zeroai.mcp.presets import install_preset, PRESETS
    install_preset("filesystem", paths=["/tmp"])  # 安装并配置
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Callable, Dict, List, Optional

from .config import MCPServerConfig, get_mcp_config


# ============================================================================
# 预设服务器配置
# ============================================================================
PRESETS: Dict[str, Dict[str, Any]] = {
    "filesystem": {
        "description": "文件系统访问（读写文件、列目录、搜索）",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "extra_args": ["paths"],  # 需要用户提供的额外参数
        "extra_args_help": "允许访问的目录列表（空格分隔）",
    },
    "git": {
        "description": "Git 仓库操作（log/diff/status/blame 等）",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-git"],
        "extra_args": ["repo"],
        "extra_args_help": "Git 仓库路径（可选，默认当前目录）",
    },
    "sqlite": {
        "description": "SQLite 数据库查询（执行 SQL、列出表）",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-sqlite"],
        "extra_args": ["db_path"],
        "extra_args_help": "SQLite 数据库文件路径",
    },
    "fetch": {
        "description": "网页抓取（将 URL 内容转为 Markdown）",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "extra_args": [],
        "extra_args_help": "无需额外参数",
    },
    "memory": {
        "description": "基于知识图谱的持久化记忆",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "extra_args": [],
        "extra_args_help": "无需额外参数",
    },
    "sequential-thinking": {
        "description": "顺序思考工具（动态思维链）",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "extra_args": [],
        "extra_args_help": "无需额外参数",
    },
    "time": {
        "description": "时间日期工具（获取当前时间、时区转换）",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-time"],
        "extra_args": [],
        "extra_args_help": "无需额外参数",
    },
    "brave-search": {
        "description": "Brave 搜索引擎（需要 API Key）",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "extra_args": ["api_key"],
        "extra_args_help": "Brave Search API Key",
        "env_key": "BRAVE_API_KEY",
    },
}


# ============================================================================
# 依赖检测
# ============================================================================
def _check_command_available(cmd: str) -> bool:
    """检测命令是否可用"""
    return shutil.which(cmd) is not None


def check_preset_dependencies(preset_name: str) -> Dict[str, Any]:
    """检测预设服务器的依赖是否已安装

    Returns:
        {"available": bool, "missing": [命令列表], "install_hint": str}
    """
    preset = PRESETS.get(preset_name)
    if not preset:
        return {
            "available": False,
            "missing": [],
            "install_hint": f"未知预设: {preset_name}",
        }

    cmd = preset["command"]
    if _check_command_available(cmd):
        return {"available": True, "missing": [], "install_hint": ""}

    # 给出安装提示
    if cmd == "npx":
        hint = "请安装 Node.js: https://nodejs.org/"
    elif cmd == "uvx":
        hint = "请安装 uv: pip install uv 或 https://docs.astral.sh/uv/"
    else:
        hint = f"请安装 {cmd}"

    return {"available": False, "missing": [cmd], "install_hint": hint}


def check_all_dependencies() -> Dict[str, Dict[str, Any]]:
    """检测所有预设的依赖"""
    return {name: check_preset_dependencies(name) for name in PRESETS}


# ============================================================================
# 预设安装
# ============================================================================
def install_preset(
    preset_name: str,
    extra_args: Optional[Dict[str, Any]] = None,
    server_name: Optional[str] = None,
    enabled: bool = True,
) -> bool:
    """安装预设 MCP 服务器

    Args:
        preset_name: 预设名（filesystem/git/sqlite/fetch 等）
        extra_args: 额外参数（如 paths/db_path/api_key）
        server_name: 自定义服务器名（默认用 preset_name）
        enabled: 是否启用

    Returns:
        True 安装成功，False 失败（依赖缺失或参数无效）
    """
    preset = PRESETS.get(preset_name)
    if not preset:
        return False

    # 检测依赖
    dep = check_preset_dependencies(preset_name)
    if not dep["available"]:
        return False

    # 构造参数
    args = list(preset["args"])
    env: Dict[str, str] = {}

    extra_args = extra_args or {}
    required = preset.get("extra_args", [])

    # 处理 filesystem 的 paths 参数
    if "paths" in required:
        paths = extra_args.get("paths", "")
        if isinstance(paths, list):
            paths = " ".join(paths)
        if paths:
            args.append(paths)

    # 处理 sqlite 的 db_path
    if "db_path" in required:
        db_path = extra_args.get("db_path", "")
        if db_path:
            args.append(db_path)

    # 处理 git 的 repo
    if "repo" in required:
        repo = extra_args.get("repo", "")
        if repo:
            args.append("--repo")
            args.append(repo)

    # 处理 api_key（作为环境变量）
    if "api_key" in required:
        api_key = extra_args.get("api_key", "")
        env_key = preset.get("env_key", f"{preset_name.upper()}_API_KEY")
        if api_key:
            env[env_key] = api_key

    # 构造配置
    config = MCPServerConfig(
        name=server_name or preset_name,
        transport=preset["transport"],
        command=preset["command"],
        args=args,
        env=env,
        enabled=enabled,
        description=preset["description"],
    )

    return get_mcp_config().add_server(config)


def uninstall_preset(preset_name: str) -> bool:
    """卸载预设服务器"""
    return get_mcp_config().remove_server(preset_name)


def list_presets() -> List[Dict[str, Any]]:
    """列出所有预设及其安装状态"""
    result = []
    for name, preset in PRESETS.items():
        dep = check_preset_dependencies(name)
        cfg = get_mcp_config().get_server(name)
        result.append({
            "name": name,
            "description": preset["description"],
            "command": preset["command"],
            "dependencies_available": dep["available"],
            "install_hint": dep["install_hint"],
            "installed": cfg is not None,
            "enabled": cfg.enabled if cfg else False,
        })
    return result


def get_preset_info(preset_name: str) -> Optional[Dict[str, Any]]:
    """获取单个预设的详细信息"""
    preset = PRESETS.get(preset_name)
    if not preset:
        return None
    dep = check_preset_dependencies(preset_name)
    cfg = get_mcp_config().get_server(preset_name)
    return {
        "name": preset_name,
        "description": preset["description"],
        "command": preset["command"],
        "args": preset["args"],
        "extra_args": preset.get("extra_args", []),
        "extra_args_help": preset.get("extra_args_help", ""),
        "dependencies_available": dep["available"],
        "install_hint": dep["install_hint"],
        "installed": cfg is not None,
        "config": cfg.to_dict() if cfg else None,
    }


__all__ = [
    "PRESETS",
    "check_preset_dependencies",
    "check_all_dependencies",
    "install_preset",
    "uninstall_preset",
    "list_presets",
    "get_preset_info",
]
