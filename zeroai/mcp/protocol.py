"""MCP 协议核心 - JSON-RPC 2.0 + Model Context Protocol 规范

实现 MCP 标准协议的消息类型和编解码，不依赖任何外部 MCP SDK。
基于 Anthropic 公开的 MCP 规范：https://modelcontextprotocol.io/

核心概念：
1. JSON-RPC 2.0：传输层协议（请求/响应/通知）
2. MCP 方法：initialize / tools/list / tools/call / resources/list 等
3. 传输方式：stdio（子进程） / SSE（HTTP 流）

本模块只负责消息格式，不涉及传输细节（传输在 client.py / server.py 中实现）。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Union


# ============================================================================
# MCP 协议版本
# ============================================================================
MCP_PROTOCOL_VERSION = "2024-11-05"

# MCP 方法常量
METHOD_INITIALIZE = "initialize"
METHOD_INITIALIZED = "notifications/initialized"
METHOD_LIST_TOOLS = "tools/list"
METHOD_CALL_TOOL = "tools/call"
METHOD_LIST_RESOURCES = "resources/list"
METHOD_READ_RESOURCE = "resources/read"
METHOD_LIST_PROMPTS = "prompts/list"
METHOD_GET_PROMPT = "prompts/get"
METHOD_PING = "ping"
METHOD_SHUTDOWN = "shutdown"


# ============================================================================
# JSON-RPC 2.0 消息类型
# ============================================================================
@dataclass
class JSONRPCRequest:
    """JSON-RPC 2.0 请求"""
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Union[int, str] = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> Dict[str, Any]:
        d = {"jsonrpc": "2.0", "method": self.method, "id": self.id}
        if self.params is not None:
            d["params"] = self.params
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class JSONRPCNotification:
    """JSON-RPC 2.0 通知（无 id，不期望响应）"""
    method: str
    params: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"jsonrpc": "2.0", "method": self.method}
        if self.params is not None:
            d["params"] = self.params
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class JSONRPCResponse:
    """JSON-RPC 2.0 响应"""
    id: Union[int, str]
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"jsonrpc": "2.0", "id": self.id}
        if self.error is not None:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class JSONRPCError:
    """JSON-RPC 2.0 错误对象"""
    code: int
    message: str
    data: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


# 标准 JSON-RPC 错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# MCP 扩展错误码
MCP_TOOL_NOT_FOUND = -32001
MCP_RESOURCE_NOT_FOUND = -32002
MCP_PROMPT_NOT_FOUND = -32003
MCP_SERVER_ERROR = -32004


def make_error_response(
    req_id: Union[int, str],
    code: int,
    message: str,
    data: Optional[Any] = None,
) -> JSONRPCResponse:
    """构造错误响应"""
    return JSONRPCResponse(
        id=req_id,
        error=JSONRPCError(code=code, message=message, data=data).to_dict(),
    )


# ============================================================================
# MCP 消息解析
# ============================================================================
def parse_message(raw: str) -> Optional[Dict[str, Any]]:
    """解析 JSON-RPC 消息

    Args:
        raw: 原始 JSON 字符串

    Returns:
        解析后的消息字典，解析失败返回 None
    """
    try:
        msg = json.loads(raw)
        if not isinstance(msg, dict):
            return None
        if msg.get("jsonrpc") != "2.0":
            return None
        return msg
    except (json.JSONDecodeError, TypeError):
        return None


def is_request(msg: Dict[str, Any]) -> bool:
    """是否为请求（有 method 和 id）"""
    return "method" in msg and "id" in msg


def is_notification(msg: Dict[str, Any]) -> bool:
    """是否为通知（有 method 无 id）"""
    return "method" in msg and "id" not in msg


def is_response(msg: Dict[str, Any]) -> bool:
    """是否为响应（有 id 无 method）"""
    return "id" in msg and "method" not in msg


# ============================================================================
# MCP 工具/资源/提示词数据结构
# ============================================================================
@dataclass
class MCPTool:
    """MCP 工具定义（对应 OpenAI Function Calling 格式）"""
    name: str
    description: str
    inputSchema: Dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema,
        }

    def to_openai_function(self) -> Dict[str, Any]:
        """转换为 OpenAI Function Calling 格式

        MCP 的 inputSchema 等价于 OpenAI 的 parameters。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.inputSchema,
            },
        }


@dataclass
class MCPResource:
    """MCP 资源定义"""
    uri: str
    name: str
    description: str = ""
    mimeType: str = "text/plain"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mimeType,
        }


@dataclass
class MCPPrompt:
    """MCP 提示词模板"""
    name: str
    description: str
    arguments: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
        }


@dataclass
class ToolCallResult:
    """工具调用结果"""
    content: List[Dict[str, Any]]  # [{"type": "text", "text": "..."}]
    isError: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"content": self.content, "isError": self.isError}

    def get_text(self) -> str:
        """提取纯文本内容"""
        parts = []
        for item in self.content:
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(parts)


def make_text_result(text: str, is_error: bool = False) -> Dict[str, Any]:
    """构造文本工具调用结果"""
    return ToolCallResult(
        content=[{"type": "text", "text": text}],
        isError=is_error,
    ).to_dict()


# ============================================================================
# MCP 初始化握手
# ============================================================================
@dataclass
class ClientInfo:
    """MCP 客户端信息"""
    name: str = "zeroai"
    version: str = "1.1.3"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version}


@dataclass
class ServerInfo:
    """MCP 服务器信息"""
    name: str = ""
    version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version}


@dataclass
class ClientCapabilities:
    """客户端能力声明"""
    roots: Optional[Dict[str, Any]] = None  # {"listChanged": True}
    sampling: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.roots is not None:
            d["roots"] = self.roots
        if self.sampling is not None:
            d["sampling"] = self.sampling
        return d


@dataclass
class ServerCapabilities:
    """服务器能力声明"""
    tools: Optional[Dict[str, Any]] = None  # {"listChanged": True}
    resources: Optional[Dict[str, Any]] = None  # {"listChanged": True, "subscribe": True}
    prompts: Optional[Dict[str, Any]] = None  # {"listChanged": True}
    logging: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.tools is not None:
            d["tools"] = self.tools
        if self.resources is not None:
            d["resources"] = self.resources
        if self.prompts is not None:
            d["prompts"] = self.prompts
        if self.logging is not None:
            d["logging"] = self.logging
        return d

    def supports_tools(self) -> bool:
        return self.tools is not None

    def supports_resources(self) -> bool:
        return self.resources is not None

    def supports_prompts(self) -> bool:
        return self.prompts is not None


def build_initialize_params(
    client_info: ClientInfo,
    capabilities: ClientCapabilities,
    protocol_version: str = MCP_PROTOCOL_VERSION,
) -> Dict[str, Any]:
    """构造 initialize 方法的参数"""
    return {
        "protocolVersion": protocol_version,
        "capabilities": capabilities.to_dict(),
        "clientInfo": client_info.to_dict(),
    }


def parse_initialize_result(result: Any) -> tuple:
    """解析 initialize 方法的结果

    Returns:
        (server_info_dict, capabilities_dict, protocol_version)
    """
    if not isinstance(result, dict):
        return {}, {}, MCP_PROTOCOL_VERSION
    return (
        result.get("serverInfo", {}),
        result.get("capabilities", {}),
        result.get("protocolVersion", MCP_PROTOCOL_VERSION),
    )


__all__ = [
    # 版本与方法
    "MCP_PROTOCOL_VERSION",
    "METHOD_INITIALIZE", "METHOD_INITIALIZED",
    "METHOD_LIST_TOOLS", "METHOD_CALL_TOOL",
    "METHOD_LIST_RESOURCES", "METHOD_READ_RESOURCE",
    "METHOD_LIST_PROMPTS", "METHOD_GET_PROMPT",
    "METHOD_PING", "METHOD_SHUTDOWN",
    # JSON-RPC 消息
    "JSONRPCRequest", "JSONRPCNotification", "JSONRPCResponse", "JSONRPCError",
    "make_error_response",
    "PARSE_ERROR", "INVALID_REQUEST", "METHOD_NOT_FOUND",
    "INVALID_PARAMS", "INTERNAL_ERROR",
    "MCP_TOOL_NOT_FOUND", "MCP_RESOURCE_NOT_FOUND",
    "MCP_PROMPT_NOT_FOUND", "MCP_SERVER_ERROR",
    # 解析
    "parse_message", "is_request", "is_notification", "is_response",
    # MCP 数据结构
    "MCPTool", "MCPResource", "MCPPrompt", "ToolCallResult",
    "make_text_result",
    # 握手
    "ClientInfo", "ServerInfo", "ClientCapabilities", "ServerCapabilities",
    "build_initialize_params", "parse_initialize_result",
]
