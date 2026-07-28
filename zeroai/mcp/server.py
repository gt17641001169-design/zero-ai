"""MCP Server - 将 ZeroAI 工具暴露给外部 MCP 客户端

让 ZeroAI 自身作为 MCP 服务器运行，外部客户端（如 Claude Desktop、Cursor）
可以连接 ZeroAI 并使用其工具集。

工作模式：
1. stdio 模式：作为子进程运行，通过 stdin/stdout 通信
2. SSE 模式：作为 HTTP 服务运行（需要 httpx + uvicorn）

启动命令（stdio 模式）：
    python -m zeroai.mcp.server
    或
    zeroai-mcp-server

外部客户端配置（在 Claude Desktop 等的配置文件中）：
    {
      "mcpServers": {
        "zeroai": {
          "transport": "stdio",
          "command": "python",
          "args": ["-m", "zeroai.mcp.server"]
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

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
    PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND,
    INVALID_PARAMS, INTERNAL_ERROR,
    MCP_TOOL_NOT_FOUND,
)
from .config import MCPServerConfig


logger = logging.getLogger(__name__)


class MCPServer:
    """MCP 服务器 - 暴露 ZeroAI 工具给外部客户端

    使用方法：
        server = MCPServer()
        await server.run_stdio()  # 以 stdio 模式运行
    """

    def __init__(
        self,
        server_name: str = "zeroai",
        server_version: str = "1.1.3",
    ):
        self.server_info = ServerInfo(name=server_name, version=server_version)
        self.capabilities = ServerCapabilities(
            tools={"listChanged": False},
            resources={"listChanged": False, "subscribe": False},
            prompts={"listChanged": False},
        )

        # 工具/资源/提示词注册
        self._tools: Dict[str, MCPTool] = {}
        self._tool_handlers: Dict[str, Callable[..., Any]] = {}
        self._resources: Dict[str, MCPResource] = {}
        self._resource_handlers: Dict[str, Callable[[], str]] = {}
        self._prompts: Dict[str, MCPPrompt] = {}
        self._prompt_handlers: Dict[str, Callable[..., str]] = {}

        # 运行状态
        self._running = False
        self._shutdown_requested = False

    # ========================================================================
    # 注册工具/资源/提示词
    # ========================================================================
    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        """注册一个工具

        Args:
            name: 工具名
            description: 工具描述
            input_schema: 输入参数 JSON Schema
            handler: 处理函数（同步或异步，接受 kwargs 返回 str 或 dict）
        """
        self._tools[name] = MCPTool(
            name=name,
            description=description,
            inputSchema=input_schema,
        )
        self._tool_handlers[name] = handler

    def register_resource(
        self,
        uri: str,
        name: str,
        description: str,
        handler: Callable[[], str],
        mime_type: str = "text/plain",
    ) -> None:
        """注册一个资源"""
        self._resources[uri] = MCPResource(
            uri=uri,
            name=name,
            description=description,
            mimeType=mime_type,
        )
        self._resource_handlers[uri] = handler

    def register_prompt(
        self,
        name: str,
        description: str,
        arguments: List[Dict[str, Any]],
        handler: Callable[..., str],
    ) -> None:
        """注册一个提示词模板"""
        self._prompts[name] = MCPPrompt(
            name=name,
            description=description,
            arguments=arguments,
        )
        self._prompt_handlers[name] = handler

    def register_zeroai_tools(self) -> int:
        """注册 ZeroAI 内置工具集

        从 zeroai.tools.registry.TOOL_MAP 和 TOOLS 加载所有工具。

        Returns:
            注册的工具数量
        """
        try:
            from zeroai.tools.registry import TOOLS, TOOL_MAP
        except ImportError:
            logger.warning("无法导入 zeroai.tools.registry，跳过内置工具注册")
            return 0

        count = 0
        for tool_schema in TOOLS:
            fn = tool_schema.get("function", {})
            name = fn.get("name", "")
            desc = fn.get("description", "")
            params = fn.get("parameters", {"type": "object", "properties": {}})

            handler = TOOL_MAP.get(name)
            if handler is None:
                continue

            self.register_tool(name, desc, params, handler)
            count += 1

        return count

    # ========================================================================
    # 请求处理
    # ========================================================================
    async def handle_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]],
    ) -> Any:
        """处理 JSON-RPC 请求并返回结果"""
        if method == METHOD_INITIALIZE:
            return self._handle_initialize(params or {})
        elif method == METHOD_PING:
            return {}
        elif method == METHOD_LIST_TOOLS:
            return self._handle_list_tools()
        elif method == METHOD_CALL_TOOL:
            return await self._handle_call_tool(params or {})
        elif method == METHOD_LIST_RESOURCES:
            return self._handle_list_resources()
        elif method == METHOD_READ_RESOURCE:
            return self._handle_read_resource(params or {})
        elif method == METHOD_LIST_PROMPTS:
            return self._handle_list_prompts()
        elif method == METHOD_GET_PROMPT:
            return self._handle_get_prompt(params or {})
        else:
            raise ValueError(f"未知方法: {method}")

    def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 initialize 请求"""
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": self.capabilities.to_dict(),
            "serverInfo": self.server_info.to_dict(),
        }

    def _handle_list_tools(self) -> Dict[str, Any]:
        """处理 tools/list 请求"""
        return {
            "tools": [t.to_dict() for t in self._tools.values()]
        }

    async def _handle_call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 tools/call 请求"""
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        if name not in self._tool_handlers:
            return make_text_result(f"未知工具: {name}", is_error=True)

        handler = self._tool_handlers[name]
        try:
            # 调用处理器（支持同步和异步）
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = await asyncio.to_thread(handler, **arguments)

            # 标准化结果
            if isinstance(result, dict) and "content" in result:
                return result
            elif isinstance(result, str):
                return make_text_result(result)
            else:
                return make_text_result(str(result))
        except TypeError as e:
            return make_text_result(f"参数错误: {e}", is_error=True)
        except Exception as e:
            tb = traceback.format_exc()
            return make_text_result(f"工具执行错误: {e}\n{tb}", is_error=True)

    def _handle_list_resources(self) -> Dict[str, Any]:
        """处理 resources/list 请求"""
        return {
            "resources": [r.to_dict() for r in self._resources.values()]
        }

    def _handle_read_resource(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 resources/read 请求"""
        uri = params.get("uri", "")
        if uri not in self._resource_handlers:
            return {"contents": []}

        try:
            text = self._resource_handlers[uri]()
            return {
                "contents": [
                    {"uri": uri, "mimeType": "text/plain", "text": str(text)}
                ]
            }
        except Exception as e:
            return {"contents": [{"uri": uri, "text": f"读取错误: {e}"}]}

    def _handle_list_prompts(self) -> Dict[str, Any]:
        """处理 prompts/list 请求"""
        return {
            "prompts": [p.to_dict() for p in self._prompts.values()]
        }

    def _handle_get_prompt(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 prompts/get 请求"""
        name = params.get("name", "")
        args = params.get("arguments", {})

        if name not in self._prompt_handlers:
            return {"messages": []}

        try:
            text = self._prompt_handlers[name](**args)
            return {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": str(text)}}
                ]
            }
        except Exception as e:
            return {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": f"错误: {e}"}}
                ]
            }

    # ========================================================================
    # 消息分发
    # ========================================================================
    async def dispatch_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """分发消息，返回响应字典（通知返回 None）"""
        if is_request(msg):
            method = msg.get("method", "")
            params = msg.get("params")
            req_id = msg.get("id")

            try:
                result = await self.handle_request(method, params)
                return JSONRPCResponse(id=req_id, result=result).to_dict()
            except ValueError as e:
                return make_error_response(
                    req_id, METHOD_NOT_FOUND, str(e)
                ).to_dict()
            except Exception as e:
                return make_error_response(
                    req_id, INTERNAL_ERROR, str(e)
                ).to_dict()

        elif is_notification(msg):
            method = msg.get("method", "")
            if method == METHOD_INITIALIZED:
                pass  # 客户端完成初始化通知
            elif method == METHOD_SHUTDOWN:
                self._shutdown_requested = True
            return None

        return None

    # ========================================================================
    # stdio 传输
    # ========================================================================
    async def run_stdio(self) -> None:
        """以 stdio 模式运行服务器

        读取 stdin 的 JSON-RPC 消息，处理后将响应写入 stdout。
        """
        self._running = True
        loop = asyncio.get_event_loop()

        # 在 Windows 上设置 stdin 为二进制模式
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
                msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
            except Exception:
                pass

        sys.stderr.write(
            f"[ZeroAI MCP Server] 启动 stdio 模式，已注册 {len(self._tools)} 个工具\n"
        )
        sys.stderr.flush()

        while self._running and not self._shutdown_requested:
            try:
                # 异步读取一行
                line = await loop.run_in_executor(
                    None, sys.stdin.readline
                )
                if not line:
                    break  # EOF

                line = line.strip()
                if not line:
                    continue

                # 解析消息
                msg = parse_message(line)
                if msg is None:
                    resp = make_error_response(
                        "unknown", PARSE_ERROR, "消息解析失败"
                    ).to_dict()
                    sys.stdout.write(json.dumps(resp) + "\n")
                    sys.stdout.flush()
                    continue

                # 分发消息
                resp = await self.dispatch_message(msg)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    sys.stdout.flush()

            except KeyboardInterrupt:
                break
            except Exception as e:
                sys.stderr.write(f"[MCP Server] 错误: {e}\n")
                sys.stderr.flush()

        self._running = False
        sys.stderr.write("[ZeroAI MCP Server] 已关闭\n")
        sys.stderr.flush()

    async def run_sse(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """以 SSE 模式运行服务器

        需要安装 httpx 和 uvicorn：
            pip install httpx uvicorn
        """
        try:
            import uvicorn
            from starlette.applications import Starlette
            from starlette.routing import Route
            from starlette.responses import JSONResponse, StreamingResponse
        except ImportError:
            raise RuntimeError(
                "SSE 模式需要 uvicorn 和 starlette，请运行: "
                "pip install uvicorn starlette"
            )

        async def handle_mcp(request):
            """处理 MCP 请求"""
            try:
                msg = await request.json()
                resp = await self.dispatch_message(msg)
                if resp is None:
                    return JSONResponse({"status": "ok"})
                return JSONResponse(resp)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)}, status_code=500
                )

        async def sse_stream(request):
            """SSE 流（用于服务器推送通知）"""
            async def event_generator():
                while self._running:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
                    await asyncio.sleep(30)
            return StreamingResponse(event_generator(), media_type="text/event-stream")

        routes = [
            Route("/mcp", handle_mcp, methods=["POST"]),
            Route("/sse", sse_stream, methods=["GET"]),
        ]

        app = Starlette(routes=routes)
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)

        self._running = True
        sys.stderr.write(
            f"[ZeroAI MCP Server] 启动 SSE 模式 http://{host}:{port}\n"
        )
        sys.stderr.flush()

        await server.serve()


# ============================================================================
# 便捷启动函数
# ============================================================================
def create_zeroai_server(register_builtin: bool = True) -> MCPServer:
    """创建 ZeroAI MCP 服务器实例

    Args:
        register_builtin: 是否注册 ZeroAI 内置工具集

    Returns:
        MCPServer 实例
    """
    server = MCPServer(
        server_name="zeroai",
        server_version="1.1.3",
    )

    if register_builtin:
        count = server.register_zeroai_tools()
        logger.info(f"已注册 {count} 个 ZeroAI 内置工具")

    return server


async def run_stdio_server() -> None:
    """便捷函数：以 stdio 模式运行 ZeroAI MCP 服务器"""
    server = create_zeroai_server()
    await server.run_stdio()


async def run_sse_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    """便捷函数：以 SSE 模式运行 ZeroAI MCP 服务器"""
    server = create_zeroai_server()
    await server.run_sse(host=host, port=port)


__all__ = [
    "MCPServer",
    "create_zeroai_server",
    "run_stdio_server",
    "run_sse_server",
]
