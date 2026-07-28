"""ZeroAI MCP 模块 - Model Context Protocol 支持

让 ZeroAI 同时具备 MCP 客户端和服务器能力：

客户端模式（连接外部 MCP 服务器使用其工具）：
    from zeroai.mcp import initialize_mcp_tools
    result = await initialize_mcp_tools()
    # MCP 工具会自动注入 TOOL_MAP，Agent Loop 可透明调用

服务器模式（将 ZeroAI 工具暴露给外部）：
    from zeroai.mcp import run_stdio_server
    await run_stdio_server()
    # 外部客户端（如 Claude Desktop）可连接使用

模块清单：
- protocol.py：MCP 协议核心（JSON-RPC 2.0 消息类型）
- config.py：配置文件管理（~/.zeroai/mcp_config.json）
- client.py：MCP 客户端（stdio / SSE 传输）
- registry.py：工具自动注册（扫描服务器并注入 TOOL_MAP）
- server.py：MCP 服务器（暴露 ZeroAI 工具给外部）

设计原则：
1. 零外部依赖：不依赖官方 MCP SDK，纯标准库实现协议层
2. 双向支持：既是 Client 又是 Server
3. 透明集成：MCP 工具自动注入 TOOL_MAP，Agent Loop 无感知
4. 安全隔离：MCP 工具名加 mcp__ 前缀避免冲突
"""
from .protocol import (
    MCP_PROTOCOL_VERSION,
    METHOD_INITIALIZE, METHOD_INITIALIZED,
    METHOD_LIST_TOOLS, METHOD_CALL_TOOL,
    METHOD_LIST_RESOURCES, METHOD_READ_RESOURCE,
    METHOD_LIST_PROMPTS, METHOD_GET_PROMPT,
    METHOD_PING, METHOD_SHUTDOWN,
    JSONRPCRequest, JSONRPCNotification, JSONRPCResponse, JSONRPCError,
    make_error_response,
    parse_message, is_request, is_notification, is_response,
    MCPTool, MCPResource, MCPPrompt, ToolCallResult,
    make_text_result,
    ClientInfo, ServerInfo, ClientCapabilities, ServerCapabilities,
    build_initialize_params, parse_initialize_result,
    PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND,
    INVALID_PARAMS, INTERNAL_ERROR,
    MCP_TOOL_NOT_FOUND, MCP_RESOURCE_NOT_FOUND,
    MCP_PROMPT_NOT_FOUND, MCP_SERVER_ERROR,
)
from .config import (
    MCP_CONFIG_DIR,
    MCP_CONFIG_FILE,
    MCPServerConfig,
    MCPConfig,
    get_mcp_config,
    reload_mcp_config,
)
from .client import MCPClient, MCPClientError
from .registry import (
    MCP_TOOL_PREFIX,
    make_mcp_tool_name,
    parse_mcp_tool_name,
    MCPRegistry,
    get_mcp_registry,
    initialize_mcp_tools,
    shutdown_mcp_tools,
)
from .server import (
    MCPServer,
    create_zeroai_server,
    run_stdio_server,
    run_sse_server,
)
from .presets import (
    PRESETS,
    check_preset_dependencies,
    check_all_dependencies,
    install_preset,
    uninstall_preset,
    list_presets,
    get_preset_info,
)


__all__ = [
    # 协议
    "MCP_PROTOCOL_VERSION",
    "METHOD_INITIALIZE", "METHOD_INITIALIZED",
    "METHOD_LIST_TOOLS", "METHOD_CALL_TOOL",
    "METHOD_LIST_RESOURCES", "METHOD_READ_RESOURCE",
    "METHOD_LIST_PROMPTS", "METHOD_GET_PROMPT",
    "METHOD_PING", "METHOD_SHUTDOWN",
    "JSONRPCRequest", "JSONRPCNotification", "JSONRPCResponse", "JSONRPCError",
    "make_error_response",
    "parse_message", "is_request", "is_notification", "is_response",
    "MCPTool", "MCPResource", "MCPPrompt", "ToolCallResult",
    "make_text_result",
    "ClientInfo", "ServerInfo", "ClientCapabilities", "ServerCapabilities",
    "build_initialize_params", "parse_initialize_result",
    "PARSE_ERROR", "INVALID_REQUEST", "METHOD_NOT_FOUND",
    "INVALID_PARAMS", "INTERNAL_ERROR",
    "MCP_TOOL_NOT_FOUND", "MCP_RESOURCE_NOT_FOUND",
    "MCP_PROMPT_NOT_FOUND", "MCP_SERVER_ERROR",
    # 配置
    "MCP_CONFIG_DIR", "MCP_CONFIG_FILE",
    "MCPServerConfig", "MCPConfig",
    "get_mcp_config", "reload_mcp_config",
    # 客户端
    "MCPClient", "MCPClientError",
    # 注册器
    "MCP_TOOL_PREFIX",
    "make_mcp_tool_name", "parse_mcp_tool_name",
    "MCPRegistry", "get_mcp_registry",
    "initialize_mcp_tools", "shutdown_mcp_tools",
    # 服务器
    "MCPServer",
    "create_zeroai_server",
    "run_stdio_server", "run_sse_server",
    # 预设
    "PRESETS",
    "check_preset_dependencies", "check_all_dependencies",
    "install_preset", "uninstall_preset",
    "list_presets", "get_preset_info",
]
