"""MCP Client - 连接外部 MCP 服务器并调用其工具

支持两种传输方式：
1. stdio：启动子进程，通过 stdin/stdout 通信（适合本地工具）
2. SSE：通过 HTTP 流通信（适合远程服务器）

核心流程：
1. 启动并完成 initialize 握手
2. 调用 tools/list 获取可用工具列表
3. 调用 tools/call 执行工具
4. 关闭连接时发送 shutdown

线程安全：每个 client 实例只能在单一线程中使用，多个并发请求自动排队。
异步设计：所有 I/O 操作均为 async，不阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .protocol import (
    MCP_PROTOCOL_VERSION,
    METHOD_INITIALIZE, METHOD_INITIALIZED,
    METHOD_LIST_TOOLS, METHOD_CALL_TOOL,
    METHOD_LIST_RESOURCES, METHOD_READ_RESOURCE,
    METHOD_LIST_PROMPTS, METHOD_GET_PROMPT,
    METHOD_PING, METHOD_SHUTDOWN,
    JSONRPCRequest, JSONRPCNotification, JSONRPCResponse,
    make_error_response,
    parse_message, is_request, is_notification, is_response,
    MCPTool, MCPResource, MCPPrompt, ToolCallResult,
    ClientInfo, ServerInfo, ClientCapabilities, ServerCapabilities,
    build_initialize_params, parse_initialize_result,
    make_text_result,
    MCP_TOOL_NOT_FOUND, MCP_SERVER_ERROR, INTERNAL_ERROR,
)
from .config import MCPServerConfig


class MCPClientError(Exception):
    """MCP 客户端错误"""
    pass


class MCPClient:
    """MCP 客户端 - 连接单个 MCP 服务器

    使用方法：
        client = MCPClient(config)
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("tool_name", {"arg": "value"})
        await client.close()
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.name = config.name

        # 连接状态
        self._connected = False
        self._initialized = False

        # 服务器信息（握手后填充）
        self.server_info: ServerInfo = ServerInfo()
        self.server_capabilities: ServerCapabilities = ServerCapabilities()
        self.protocol_version: str = MCP_PROTOCOL_VERSION

        # 工具列表缓存
        self._tools_cache: Optional[List[MCPTool]] = None
        self._resources_cache: Optional[List[MCPResource]] = None
        self._prompts_cache: Optional[List[MCPPrompt]] = None

        # 传输层（stdio 或 SSE，由 _connect_* 设置）
        self._process: Optional[asyncio.subprocess.Process] = None
        self._sse_session: Optional[Any] = None  # httpx.AsyncClient（延迟导入）

        # 请求/响应匹配
        self._pending: Dict[str, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._read_task: Optional[asyncio.Task] = None

    # ========================================================================
    # 连接管理
    # ========================================================================
    async def connect(self) -> bool:
        """建立连接并完成 initialize 握手

        Returns:
            True 连接成功，False 连接失败
        """
        if self._connected:
            return True

        try:
            if self.config.transport == "stdio":
                await self._connect_stdio()
            elif self.config.transport == "sse":
                await self._connect_sse()
            else:
                raise MCPClientError(f"不支持的传输方式: {self.config.transport}")

            # 启动读取循环
            self._read_task = asyncio.create_task(self._read_loop())

            # 完成 initialize 握手
            await self._do_initialize()

            self._connected = True
            return True
        except Exception as e:
            await self.close()
            raise MCPClientError(f"连接 MCP 服务器 {self.name} 失败: {e}")

    async def close(self) -> None:
        """关闭连接"""
        if not self._connected and not self._process and not self._sse_session:
            return

        # 发送 shutdown 通知（best effort，不等待响应）
        try:
            if self._initialized:
                await self._send_notification(METHOD_SHUTDOWN, {})
        except Exception:
            pass

        # 取消读取任务
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):
                pass
            self._read_task = None

        # 关闭子进程
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
            except Exception:
                pass
            self._process = None

        # 关闭 SSE 会话
        if self._sse_session:
            try:
                await self._sse_session.aclose()
            except Exception:
                pass
            self._sse_session = None

        # 取消所有 pending 请求
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(MCPClientError("连接已关闭"))
        self._pending.clear()

        self._connected = False
        self._initialized = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._initialized

    # ========================================================================
    # stdio 传输
    # ========================================================================
    async def _connect_stdio(self) -> None:
        """通过 stdio 启动子进程"""
        cmd = [self.config.command] + list(self.config.args)
        env = self.config.build_env()
        cwd = self.config.cwd or None

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )
        except FileNotFoundError as e:
            raise MCPClientError(f"命令不存在: {self.config.command} ({e})")
        except OSError as e:
            raise MCPClientError(f"启动子进程失败: {e}")

    async def _connect_sse(self) -> None:
        """通过 SSE 连接服务器

        延迟导入 httpx，避免无 SSE 服务器时强制依赖。
        """
        try:
            import httpx
        except ImportError:
            raise MCPClientError("SSE 模式需要 httpx，请运行: pip install httpx")

        self._sse_session = httpx.AsyncClient(
            base_url=self.config.url,
            headers=self.config.headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

        # 测试连接
        try:
            resp = await self._sse_session.get("/")
            if resp.status_code >= 500:
                raise MCPClientError(f"服务器错误: HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            raise MCPClientError(f"无法连接 SSE 服务器: {e}")

    # ========================================================================
    # 读取循环
    # ========================================================================
    async def _read_loop(self) -> None:
        """读取循环：从传输层读取消息并分发到对应的 Future"""
        while True:
            try:
                raw = await self._read_one_message()
                if raw is None:
                    break
                msg = parse_message(raw)
                if msg is None:
                    continue
                await self._dispatch_message(msg)
            except asyncio.CancelledError:
                break
            except Exception:
                # 读取异常不退出循环，尝试继续
                continue

    async def _read_one_message(self) -> Optional[str]:
        """读取一条完整消息"""
        if self._process:
            # stdio 模式：按行读取
            line = await self._process.stdout.readline()
            if not line:
                return None
            return line.decode("utf-8", errors="ignore").strip()
        elif self._sse_session:
            # SSE 模式：通过 HTTP POST 发送请求，通过 SSE 流读取响应
            # 简化实现：用 POST + 轮询模式
            return await self._sse_read_one()
        return None

    async def _sse_read_one(self) -> Optional[str]:
        """SSE 模式读取消息（简化：同步请求/响应）"""
        # SSE 模式下，_read_one_message 由 _send_request 内联处理
        # 这里返回 None 让 _read_loop 退出
        return None

    async def _dispatch_message(self, msg: Dict[str, Any]) -> None:
        """分发消息到对应的 Future 或处理通知"""
        if is_response(msg):
            req_id = str(msg.get("id", ""))
            fut = self._pending.pop(req_id, None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(
                        MCPClientError(f"服务器返回错误: {msg['error']}")
                    )
                else:
                    fut.set_result(msg.get("result"))
        elif is_request(msg):
            # 服务器发起的请求（如 sampling）暂不处理
            pass
        elif is_notification(msg):
            # 通知（如 tools/list_changed）暂不处理
            pass

    # ========================================================================
    # 发送请求
    # ========================================================================
    async def _send_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Any:
        """发送 JSON-RPC 请求并等待响应"""
        if not self._process and not self._sse_session:
            raise MCPClientError("未连接到服务器")

        req = JSONRPCRequest(method=method, params=params)
        req_id = str(req.id)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut

        raw = req.to_json() + "\n"

        try:
            async with self._write_lock:
                if self._process:
                    self._process.stdin.write(raw.encode("utf-8"))
                    await self._process.stdin.drain()
                elif self._sse_session:
                    # SSE 模式：用 POST 发送请求，直接读取响应
                    resp = await self._sse_session.post("/mcp", json=req.to_dict())
                    if resp.status_code != 200:
                        raise MCPClientError(f"HTTP 错误: {resp.status_code}")
                    result = resp.json()
                    if "error" in result:
                        raise MCPClientError(f"服务器返回错误: {result['error']}")
                    return result.get("result")

            # stdio 模式：等待 _read_loop 分发结果
            if self._process:
                return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise MCPClientError(f"请求 {method} 超时（{timeout}s）")
        except BrokenPipeError:
            self._pending.pop(req_id, None)
            raise MCPClientError("连接已断开（管道破裂）")
        except asyncio.CancelledError:
            self._pending.pop(req_id, None)
            raise

    async def _send_notification(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """发送 JSON-RPC 通知（不等待响应）"""
        if not self._process and not self._sse_session:
            return

        notif = JSONRPCNotification(method=method, params=params)
        raw = notif.to_json() + "\n"

        try:
            async with self._write_lock:
                if self._process:
                    self._process.stdin.write(raw.encode("utf-8"))
                    await self._process.stdin.drain()
                elif self._sse_session:
                    await self._sse_session.post("/mcp", json=notif.to_dict())
        except (BrokenPipeError, Exception):
            pass

    # ========================================================================
    # MCP 协议方法
    # ========================================================================
    async def _do_initialize(self) -> None:
        """完成 initialize 握手"""
        client_info = ClientInfo(name="zeroai", version="1.1.3")
        capabilities = ClientCapabilities()
        params = build_initialize_params(client_info, capabilities)

        result = await self._send_request(METHOD_INITIALIZE, params, timeout=15.0)

        server_info_dict, caps_dict, proto_ver = parse_initialize_result(result)
        self.server_info = ServerInfo(
            name=server_info_dict.get("name", ""),
            version=server_info_dict.get("version", ""),
        )

        # 解析服务器能力
        self.server_capabilities = ServerCapabilities(
            tools=caps_dict.get("tools"),
            resources=caps_dict.get("resources"),
            prompts=caps_dict.get("prompts"),
            logging=caps_dict.get("logging"),
        )
        self.protocol_version = proto_ver

        # 发送 initialized 通知
        await self._send_notification(METHOD_INITIALIZED, {})
        self._initialized = True

    async def ping(self) -> bool:
        """心跳检测"""
        try:
            await self._send_request(METHOD_PING, {}, timeout=5.0)
            return True
        except Exception:
            return False

    async def list_tools(self, refresh: bool = False) -> List[MCPTool]:
        """获取工具列表"""
        if self._tools_cache and not refresh:
            return self._tools_cache

        if not self.server_capabilities.supports_tools():
            return []

        result = await self._send_request(METHOD_LIST_TOOLS, {})
        tools_data = result.get("tools", []) if isinstance(result, dict) else []
        self._tools_cache = [
            MCPTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
            )
            for t in tools_data
            if isinstance(t, dict)
        ]
        return self._tools_cache

    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """调用工具

        Args:
            tool_name: 工具名
            arguments: 工具参数
            timeout: 超时时间

        Returns:
            工具调用结果（含 content 和 isError 字段）
        """
        params = {"name": tool_name, "arguments": arguments or {}}
        try:
            result = await self._send_request(
                METHOD_CALL_TOOL, params, timeout=timeout
            )
            if not isinstance(result, dict):
                return make_text_result(str(result))
            return result
        except MCPClientError as e:
            return make_text_result(str(e), is_error=True)

    async def list_resources(self, refresh: bool = False) -> List[MCPResource]:
        """获取资源列表"""
        if self._resources_cache and not refresh:
            return self._resources_cache

        if not self.server_capabilities.supports_resources():
            return []

        result = await self._send_request(METHOD_LIST_RESOURCES, {})
        res_data = result.get("resources", []) if isinstance(result, dict) else []
        self._resources_cache = [
            MCPResource(
                uri=r.get("uri", ""),
                name=r.get("name", ""),
                description=r.get("description", ""),
                mimeType=r.get("mimeType", "text/plain"),
            )
            for r in res_data
            if isinstance(r, dict)
        ]
        return self._resources_cache

    async def read_resource(self, uri: str) -> str:
        """读取资源内容"""
        params = {"uri": uri}
        result = await self._send_request(METHOD_READ_RESOURCE, params)
        if isinstance(result, dict):
            contents = result.get("contents", [])
            if contents and isinstance(contents, list):
                first = contents[0]
                if isinstance(first, dict):
                    return first.get("text", "")
        return ""

    async def list_prompts(self, refresh: bool = False) -> List[MCPPrompt]:
        """获取提示词列表"""
        if self._prompts_cache and not refresh:
            return self._prompts_cache

        if not self.server_capabilities.supports_prompts():
            return []

        result = await self._send_request(METHOD_LIST_PROMPTS, {})
        p_data = result.get("prompts", []) if isinstance(result, dict) else []
        self._prompts_cache = [
            MCPPrompt(
                name=p.get("name", ""),
                description=p.get("description", ""),
                arguments=p.get("arguments", []),
            )
            for p in p_data
            if isinstance(p, dict)
        ]
        return self._prompts_cache

    async def get_prompt(
        self,
        name: str,
        arguments: Optional[Dict[str, str]] = None,
    ) -> str:
        """获取提示词内容"""
        params = {"name": name, "arguments": arguments or {}}
        result = await self._send_request(METHOD_GET_PROMPT, params)
        if isinstance(result, dict):
            messages = result.get("messages", [])
            if messages and isinstance(messages, list):
                first = messages[0]
                if isinstance(first, dict):
                    content = first.get("content", {})
                    if isinstance(content, dict):
                        return content.get("text", "")
        return ""

    # ========================================================================
    # 便捷方法
    # ========================================================================
    def get_openai_tools_schema(self) -> List[Dict[str, Any]]:
        """获取 OpenAI Function Calling 格式的工具 schema

        供 ZeroAI 的 TOOLS 列表合并使用。
        """
        if not self._tools_cache:
            return []
        return [t.to_openai_function() for t in self._tools_cache]


__all__ = [
    "MCPClient",
    "MCPClientError",
]
