"""MCP 工具生态管理（阶段 F.1 + F.2）

提供：
- F.1 官方 MCP 服务器接入管理（批量启用/禁用/状态查询）
- F.2 MCP 工具与 ZeroAI 工具统一调度（冲突检测、命名空间隔离）

设计原则：
- 增量追加：不修改 presets.py / registry.py 原有代码
- 冲突检测：MCP 工具名与内置工具名冲突时自动重命名
- 统一调度：通过 unified_call_tool 统一入口调用内置和 MCP 工具
- 向后兼容：原有 TOOL_MAP / TOOLS 保持不变

使用方式：
    from zeroai.mcp.ecosystem import get_ecosystem_manager
    mgr = get_ecosystem_manager()
    # 批量启用预设
    await mgr.enable_presets(["filesystem", "git"])
    # 检测冲突
    conflicts = mgr.detect_conflicts()
    # 统一调用
    result = await mgr.call_tool("read_file", {"path": "/tmp/test"})
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .config import MCPServerConfig, get_mcp_config
from .presets import (
    PRESETS,
    check_preset_dependencies,
    install_preset,
    list_presets,
    get_preset_info,
)
from .registry import (
    MCP_TOOL_PREFIX,
    get_mcp_registry,
    initialize_mcp_tools,
    shutdown_mcp_tools,
)


# ============================================================================
# 冲突检测数据结构
# ============================================================================

@dataclass
class ToolConflict:
    """工具命名冲突"""
    tool_name: str
    builtin_source: str  # 内置工具来源模块
    mcp_server: str  # MCP 服务器名
    resolution: str = ""  # 解决策略：rename_mcp / disable_mcp / allow_override
    resolved_name: str = ""  # 解决后的名称


@dataclass
class EcosystemStatus:
    """生态系统状态报告"""
    total_presets: int = 0
    installed_presets: int = 0
    enabled_servers: int = 0
    connected_servers: int = 0
    total_mcp_tools: int = 0
    builtin_tools: int = 0
    conflicts: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 生态系统管理器
# ============================================================================

class MCPEcosystemManager:
    """MCP 工具生态管理器

    单例模式，统一管理 MCP 预设、服务器、工具注册和冲突检测。
    """

    def __init__(self):
        self._conflicts_cache: List[ToolConflict] = []
        self._renamed_tools: Dict[str, str] = {}  # 原名 -> 重命名后
        self._enabled_presets: Set[str] = set()

    # ========================================================================
    # F.1: 预设管理
    # ========================================================================

    def list_available_presets(self) -> List[Dict[str, Any]]:
        """列出所有可用预设

        Returns:
            预设信息列表，包含依赖状态
        """
        # list_presets() 返回字典列表，每个字典含 name/description/command 等
        presets = list_presets()
        result = []
        for preset_info in presets:
            name = preset_info.get("name", "")
            if not name:
                continue
            deps_ok = preset_info.get("dependencies_available", False)
            missing_hint = preset_info.get("install_hint", "")
            result.append({
                "name": name,
                "description": preset_info.get("description", ""),
                "transport": "stdio",  # 所有预设默认 stdio
                "command": preset_info.get("command", ""),
                "deps_available": deps_ok,
                "missing_deps": missing_hint,
                "is_installed": preset_info.get("installed", False),
                "is_enabled": preset_info.get("enabled", False),
            })
        return result

    def _is_preset_installed(self, preset_name: str) -> bool:
        """检查预设是否已安装到配置文件"""
        config = get_mcp_config()
        server = config.get_server(preset_name)
        return server is not None

    async def enable_preset(
        self,
        preset_name: str,
        **preset_args: Any,
    ) -> Tuple[bool, str]:
        """启用单个预设

        Args:
            preset_name: 预设名称
            **preset_args: 预设参数（如 paths for filesystem, db_path for sqlite）

        Returns:
            (成功标志, 消息)
        """
        if preset_name not in PRESETS:
            return False, f"未知预设: {preset_name}"

        # 检查依赖
        deps_ok, missing = check_preset_dependencies(preset_name)
        if not deps_ok:
            return False, f"依赖缺失: {', '.join(missing)}"

        # 安装预设
        success = install_preset(preset_name, **preset_args)
        if not success:
            return False, f"安装预设 {preset_name} 失败"

        self._enabled_presets.add(preset_name)
        return True, f"预设 {preset_name} 已启用"

    async def enable_presets(
        self,
        preset_names: List[str],
        preset_args: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Tuple[bool, str]]:
        """批量启用预设

        Args:
            preset_names: 预设名称列表
            preset_args: 每个预设的参数 {preset_name: {param: value}}

        Returns:
            {preset_name: (success, message)}
        """
        results: Dict[str, Tuple[bool, str]] = {}
        preset_args = preset_args or {}

        for name in preset_names:
            args = preset_args.get(name, {})
            success, msg = await self.enable_preset(name, **args)
            results[name] = (success, msg)

        return results

    async def disable_preset(self, preset_name: str) -> Tuple[bool, str]:
        """禁用预设

        Args:
            preset_name: 预设名称

        Returns:
            (成功标志, 消息)
        """
        config = get_mcp_config()
        if not config.get_server(preset_name):
            return False, f"预设 {preset_name} 未安装"

        success = config.remove_server(preset_name)
        if success:
            self._enabled_presets.discard(preset_name)
            return True, f"预设 {preset_name} 已禁用"
        return False, f"禁用预设 {preset_name} 失败"

    async def initialize_ecosystem(self, timeout_per_server: float = 10.0) -> Dict[str, Any]:
        """初始化整个 MCP 生态系统

        1. 连接所有已启用的 MCP 服务器
        2. 检测工具命名冲突
        3. 将 MCP 工具注入 TOOL_MAP

        Args:
            timeout_per_server: 单个服务器连接超时

        Returns:
            初始化报告
        """
        # 1. 初始化 MCP 工具
        result = await initialize_mcp_tools(timeout_per_server=timeout_per_server)

        # 2. 检测冲突
        conflicts = self.detect_conflicts()
        self._conflicts_cache = conflicts

        # 3. 处理冲突
        for conflict in conflicts:
            if conflict.resolution == "rename_mcp":
                self._renamed_tools[conflict.tool_name] = conflict.resolved_name

        return {
            **result,
            "conflicts_detected": len(conflicts),
            "conflicts": [c.__dict__ for c in conflicts],
            "renamed_tools": dict(self._renamed_tools),
        }

    # ========================================================================
    # F.2: 冲突检测与统一调度
    # ========================================================================

    def detect_conflicts(self) -> List[ToolConflict]:
        """检测 MCP 工具名与内置工具名的冲突

        MCP 工具名格式为 mcp__<server>__<tool>，本身不会与内置工具冲突。
        但如果用户配置了同名 MCP 服务器和工具，可能产生冲突。
        本方法还检测 MCP 工具的原始名（不含前缀）是否与内置工具重复。

        Returns:
            冲突列表
        """
        conflicts: List[ToolConflict] = []

        try:
            # 延迟导入避免循环依赖
            from zeroai.tools.registry import TOOL_MAP

            # 获取所有 MCP 注册的工具
            mcp_registry = get_mcp_registry()
            mcp_tool_index = mcp_registry._tool_index

            # 内置工具名集合
            builtin_names: Set[str] = set(TOOL_MAP.keys())

            # 检查 MCP 工具的原始名是否与内置工具重复
            for full_name, (server_name, orig_name) in mcp_tool_index.items():
                if orig_name in builtin_names:
                    conflict = ToolConflict(
                        tool_name=orig_name,
                        builtin_source="zeroai.tools",
                        mcp_server=server_name,
                        resolution="rename_mcp",
                        resolved_name=full_name,  # 使用带前缀的完整名
                    )
                    conflicts.append(conflict)

        except Exception:
            pass

        self._conflicts_cache = conflicts
        return conflicts

    def get_conflicts(self) -> List[ToolConflict]:
        """获取最近一次检测到的冲突"""
        return list(self._conflicts_cache)

    def resolve_tool_name(self, name: str) -> str:
        """解析工具名到实际调用名

        如果用户输入的工具名与内置工具冲突，且 MCP 版本被重命名，
        返回重命名后的名称。

        Args:
            name: 用户输入的工具名

        Returns:
            实际调用的工具名
        """
        return self._renamed_tools.get(name, name)

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        """统一工具调用入口

        自动判断是内置工具还是 MCP 工具，统一调度。

        Args:
            tool_name: 工具名（内置或 MCP 完整名）
            arguments: 调用参数

        Returns:
            工具调用结果
        """
        # 解析重命名
        actual_name = self.resolve_tool_name(tool_name)

        # 1. 检查是否为 MCP 工具
        mcp_registry = get_mcp_registry()
        if mcp_registry.is_mcp_tool(actual_name):
            return await mcp_registry.call_tool(actual_name, arguments)

        # 2. 检查是否为内置工具
        try:
            from zeroai.tools.registry import TOOL_MAP
            if actual_name in TOOL_MAP:
                func = TOOL_MAP[actual_name]
                # 内置工具可能是 sync 或 async
                if asyncio.iscoroutinefunction(func):
                    return await func(**arguments)
                else:
                    result = func(**arguments)
                    return result if isinstance(result, str) else str(result)
        except Exception as e:
            return f"[错误] 工具调用失败: {e}"

        return f"[错误] 未知工具: {tool_name}"

    def get_status(self) -> EcosystemStatus:
        """获取生态系统状态报告"""
        presets = list_presets()
        config = get_mcp_config()
        servers = config.list_servers(only_enabled=True)

        mcp_registry = get_mcp_registry()
        mcp_clients = mcp_registry.clients
        connected = sum(1 for c in mcp_clients.values() if c.is_connected)
        mcp_tools_count = len(mcp_registry._tool_index)

        try:
            from zeroai.tools.registry import TOOL_MAP
            builtin_count = len(TOOL_MAP)
        except Exception:
            builtin_count = 0

        return EcosystemStatus(
            total_presets=len(presets),
            installed_presets=len(servers),
            enabled_servers=len(servers),
            connected_servers=connected,
            total_mcp_tools=mcp_tools_count,
            builtin_tools=builtin_count,
            conflicts=len(self._conflicts_cache),
            details={
                "presets": [p["name"] for p in self.list_available_presets()],
                "enabled_presets": list(self._enabled_presets),
                "connected_servers": list(mcp_clients.keys()),
                "conflicts": [c.__dict__ for c in self._conflicts_cache],
                "renamed_tools": dict(self._renamed_tools),
            },
        )

    async def shutdown(self) -> None:
        """关闭生态系统（断开所有 MCP 连接）"""
        await shutdown_mcp_tools()
        self._enabled_presets.clear()
        self._conflicts_cache.clear()
        self._renamed_tools.clear()


# ============================================================================
# 全局单例
# ============================================================================

_ecosystem_manager: Optional[MCPEcosystemManager] = None


def get_ecosystem_manager() -> MCPEcosystemManager:
    """获取全局生态系统管理器实例"""
    global _ecosystem_manager
    if _ecosystem_manager is None:
        _ecosystem_manager = MCPEcosystemManager()
    return _ecosystem_manager


def reset_ecosystem_manager() -> None:
    """重置全局生态系统管理器（主要用于测试）"""
    global _ecosystem_manager
    _ecosystem_manager = None


__all__ = [
    "ToolConflict",
    "EcosystemStatus",
    "MCPEcosystemManager",
    "get_ecosystem_manager",
    "reset_ecosystem_manager",
]
