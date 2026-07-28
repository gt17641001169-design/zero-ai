"""MCP 工具自动注册 - 扫描配置的 MCP 服务器并注入 TOOL_MAP

启动流程：
1. 读取 ~/.zeroai/mcp_config.json
2. 连接每个 enabled 的 MCP 服务器
3. 获取 tools/list
4. 为每个 MCP 工具生成包装函数，注入 TOOL_MAP 和 TOOLS

工具命名：mcp__<server_name>__<tool_name>
- 前缀 mcp__ 避免与内置工具冲突
- 中间是服务器名
- 后缀是工具原名

这样 ZeroAI 的 Agent Loop 可以透明地调用 MCP 工具，无需修改核心逻辑。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .client import MCPClient, MCPClientError
from .config import MCPServerConfig, get_mcp_config
from .protocol import MCPTool

logger = logging.getLogger(__name__)


# MCP 工具名前缀
MCP_TOOL_PREFIX = "mcp__"


def make_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """生成 MCP 工具的标准名

    格式：mcp__<server>__<tool>
    """
    # 清理 server_name（替换非法字符）
    safe_server = server_name.replace("-", "_").replace(" ", "_")
    return f"{MCP_TOOL_PREFIX}{safe_server}__{tool_name}"


def parse_mcp_tool_name(full_name: str) -> Optional[Tuple[str, str]]:
    """解析 MCP 工具名为 (server_name, tool_name)

    非 MCP 工具返回 None。
    """
    if not full_name.startswith(MCP_TOOL_PREFIX):
        return None
    rest = full_name[len(MCP_TOOL_PREFIX):]
    parts = rest.split("__", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _make_tool_wrapper(
    client: MCPClient,
    tool_name: str,
    server_name: str,
) -> Callable[..., Any]:
    """为 MCP 工具生成包装函数

    包装函数签名：async def wrapper(**kwargs) -> str
    内部调用 client.call_tool 并返回纯文本结果。
    """
    full_name = make_mcp_tool_name(server_name, tool_name)

    async def _wrapper(**kwargs: Any) -> str:
        """MCP 工具调用包装（由 _make_tool_wrapper 动态生成）"""
        try:
            # 确保客户端已连接
            if not client.is_connected:
                await client.connect()

            result = await client.call_tool(tool_name, kwargs)
            # 提取纯文本
            if isinstance(result, dict):
                content = result.get("content", [])
                is_error = result.get("isError", False)
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                text = "\n".join(parts) if parts else str(result)
                if is_error:
                    return f"[MCP 工具错误] {text}"
                return text
            return str(result)
        except MCPClientError as e:
            return f"[MCP 连接错误] {e}"
        except asyncio.TimeoutError:
            return f"[MCP 超时] 工具 {tool_name} 调用超时"
        except Exception as e:
            return f"[MCP 异常] {type(e).__name__}: {e}"

    _wrapper.__name__ = full_name
    _wrapper.__qualname__ = full_name
    _wrapper.__doc__ = f"MCP 工具：{server_name}.{tool_name}"
    return _wrapper


def _mcp_tool_to_openai_schema(
    server_name: str,
    tool: MCPTool,
) -> Dict[str, Any]:
    """将 MCP 工具转换为 OpenAI Function Calling 格式"""
    full_name = make_mcp_tool_name(server_name, tool.name)
    return {
        "type": "function",
        "function": {
            "name": full_name,
            "description": f"[MCP:{server_name}] {tool.description}",
            "parameters": tool.inputSchema,
        },
    }


class MCPRegistry:
    """MCP 工具注册器 - 管理所有已连接的 MCP 客户端

    单例模式，全局共享。
    """

    def __init__(self):
        # server_name -> MCPClient
        self._clients: Dict[str, MCPClient] = {}
        # full_tool_name -> (server_name, tool_name)
        self._tool_index: Dict[str, Tuple[str, str]] = {}
        # 已注册的工具 schema 和包装函数
        self._registered_tools: List[Dict[str, Any]] = []
        self._registered_funcs: Dict[str, Callable] = {}
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def clients(self) -> Dict[str, MCPClient]:
        return dict(self._clients)

    def get_client(self, server_name: str) -> Optional[MCPClient]:
        """获取指定服务器的客户端"""
        return self._clients.get(server_name)

    async def initialize(self, timeout_per_server: float = 10.0) -> Dict[str, Any]:
        """初始化：扫描配置并连接所有启用的 MCP 服务器

        Args:
            timeout_per_server: 单个服务器连接超时

        Returns:
            {"connected": [...], "failed": [...], "tools_added": int}
        """
        if self._initialized:
            return self._get_status()

        config = get_mcp_config()
        servers = config.list_servers(only_enabled=True)

        connected: List[str] = []
        failed: List[Tuple[str, str]] = []
        tools_added = 0

        for server_cfg in servers:
            try:
                client = MCPClient(server_cfg)
                await asyncio.wait_for(
                    client.connect(),
                    timeout=timeout_per_server,
                )
                self._clients[server_cfg.name] = client

                # 获取工具列表
                tools = await client.list_tools()
                for tool in tools:
                    full_name = make_mcp_tool_name(server_cfg.name, tool.name)
                    self._tool_index[full_name] = (server_cfg.name, tool.name)

                    # 生成 schema 和包装函数
                    schema = _mcp_tool_to_openai_schema(server_cfg.name, tool)
                    wrapper = _make_tool_wrapper(client, tool.name, server_cfg.name)

                    self._registered_tools.append(schema)
                    self._registered_funcs[full_name] = wrapper
                    tools_added += 1

                connected.append(server_cfg.name)
            except asyncio.TimeoutError:
                failed.append((server_cfg.name, "连接超时"))
            except Exception as e:
                failed.append((server_cfg.name, str(e)))

        self._initialized = True
        return {
            "connected": connected,
            "failed": failed,
            "tools_added": tools_added,
        }

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """获取所有 MCP 工具的 OpenAI schema"""
        return list(self._registered_tools)

    def get_tool_functions(self) -> Dict[str, Callable]:
        """获取所有 MCP 工具的包装函数"""
        return dict(self._registered_funcs)

    def is_mcp_tool(self, tool_name: str) -> bool:
        """判断是否为 MCP 工具"""
        return tool_name in self._tool_index

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        """直接调用 MCP 工具（不走 TOOL_MAP）"""
        if tool_name not in self._tool_index:
            return f"[错误] 未知 MCP 工具: {tool_name}"

        server_name, orig_name = self._tool_index[tool_name]
        client = self._clients.get(server_name)
        if not client:
            return f"[错误] MCP 服务器 {server_name} 未连接"

        try:
            if not client.is_connected:
                await client.connect()
            result = await client.call_tool(orig_name, arguments)
            if isinstance(result, dict):
                content = result.get("content", [])
                parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                return "\n".join(parts) if parts else str(result)
            return str(result)
        except Exception as e:
            return f"[MCP 调用错误] {e}"

    async def refresh_server(self, server_name: str) -> bool:
        """刷新单个服务器的工具列表"""
        client = self._clients.get(server_name)
        if not client:
            return False

        try:
            # 移除旧工具
            old_names = [
                name for name, (s, _) in self._tool_index.items()
                if s == server_name
            ]
            for name in old_names:
                self._tool_index.pop(name, None)
                self._registered_funcs.pop(name, None)

            self._registered_tools = [
                t for t in self._registered_tools
                if not t.get("function", {}).get("name", "").startswith(
                    f"{MCP_TOOL_PREFIX}{server_name}__"
                )
            ]

            # 重新获取
            tools = await client.list_tools(refresh=True)
            for tool in tools:
                full_name = make_mcp_tool_name(server_name, tool.name)
                self._tool_index[full_name] = (server_name, tool.name)
                schema = _mcp_tool_to_openai_schema(server_name, tool)
                wrapper = _make_tool_wrapper(client, tool.name, server_name)
                self._registered_tools.append(schema)
                self._registered_funcs[full_name] = wrapper
            return True
        except Exception:
            return False

    async def shutdown(self) -> None:
        """关闭所有客户端"""
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()
        self._tool_index.clear()
        self._registered_tools.clear()
        self._registered_funcs.clear()
        self._initialized = False

    def _get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "connected": list(self._clients.keys()),
            "failed": [],
            "tools_added": len(self._registered_tools),
        }

    def get_status_text(self) -> str:
        """获取人类可读的状态文本"""
        if not self._initialized:
            return "MCP 注册器未初始化"

        lines = [f"MCP 服务器: {len(self._clients)} 个已连接"]
        for name, client in self._clients.items():
            tools_count = sum(
                1 for n, (s, _) in self._tool_index.items() if s == name
            )
            lines.append(f"  - {name}: {tools_count} 工具")
        lines.append(f"MCP 工具总数: {len(self._registered_tools)}")
        return "\n".join(lines)


# ============================================================================
# 全局单例
# ============================================================================
_registry_instance: Optional[MCPRegistry] = None


def get_mcp_registry() -> MCPRegistry:
    """获取全局 MCP 注册器"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = MCPRegistry()
    return _registry_instance


async def initialize_mcp_tools(timeout_per_server: float = 10.0) -> Dict[str, Any]:
    """初始化 MCP 工具并注入 TOOL_MAP

    使用方法（在 ZeroAI 启动时调用）：
        from zeroai.mcp import initialize_mcp_tools
        result = await initialize_mcp_tools()
        if result["tools_added"] > 0:
            print(f"已加载 {result['tools_added']} 个 MCP 工具")

    Returns:
        {"connected": [...], "failed": [...], "tools_added": int}
    """
    registry = get_mcp_registry()
    result = await registry.initialize(timeout_per_server=timeout_per_server)

    # 注入到 TOOL_MAP 和 TOOLS（延迟导入避免循环依赖）
    try:
        from zeroai.tools.registry import TOOLS, TOOL_MAP

        mcp_tools = registry.get_tools_schema()
        mcp_funcs = registry.get_tool_functions()

        for name, func in mcp_funcs.items():
            TOOL_MAP[name] = func

        for schema in mcp_tools:
            # 避免重复添加
            name = schema.get("function", {}).get("name", "")
            if name and not any(
                t.get("function", {}).get("name") == name for t in TOOLS
            ):
                TOOLS.append(schema)
    except Exception as e:
        logger.warning(f"注入 MCP 工具到 TOOL_MAP 失败: {e}")

    return result


async def shutdown_mcp_tools() -> None:
    """关闭所有 MCP 连接（在 ZeroAI 退出时调用）"""
    registry = get_mcp_registry()
    await registry.shutdown()


__all__ = [
    "MCP_TOOL_PREFIX",
    "make_mcp_tool_name",
    "parse_mcp_tool_name",
    "MCPRegistry",
    "get_mcp_registry",
    "initialize_mcp_tools",
    "shutdown_mcp_tools",
]
