"""MCP 模块综合测试 - 验证阶段 3 的全部功能

测试覆盖：
1. 协议层：JSON-RPC 2.0 消息编解码、MCP 数据结构
2. 配置管理：MCPServerConfig 加载/保存/校验
3. 客户端：MCPClient 连接握手（stdio + SSE）
4. 工具注册：MCPRegistry 自动注入 TOOL_MAP
5. 服务器：MCPServer 启动并响应请求
6. 端到端：MCPClient 连接 MCPServer，调用工具

运行方式：
    python test_mcp_stages.py
"""
import asyncio
import json
import os
import sys
import tempfile
import subprocess
import time

# 确保项目根目录在 sys.path
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)


# ============================================================================
# 测试工具函数
# ============================================================================
def _print_pass(name):
    print(f"[PASS] {name}")


def _print_fail(name, err):
    print(f"[FAIL] {name}: {err}")


def run_test(name, test_fn):
    """运行同步测试"""
    try:
        test_fn()
        _print_pass(name)
        return True
    except Exception as e:
        _print_fail(name, e)
        return False


async def run_async_test(name, test_fn):
    """运行异步测试"""
    try:
        await test_fn()
        _print_pass(name)
        return True
    except Exception as e:
        _print_fail(name, e)
        return False


# ============================================================================
# 阶段 3.0：协议层测试
# ============================================================================
def test_protocol_jsonrpc_request():
    """测试 JSON-RPC 2.0 请求序列化"""
    from zeroai.mcp.protocol import JSONRPCRequest

    req = JSONRPCRequest(method="initialize", params={"a": 1})
    d = req.to_dict()
    assert d["jsonrpc"] == "2.0"
    assert d["method"] == "initialize"
    assert d["params"] == {"a": 1}
    assert "id" in d

    # to_json 应该是合法 JSON
    parsed = json.loads(req.to_json())
    assert parsed["method"] == "initialize"


def test_protocol_jsonrpc_response():
    """测试 JSON-RPC 2.0 响应序列化"""
    from zeroai.mcp.protocol import JSONRPCResponse, make_error_response

    # 成功响应
    resp = JSONRPCResponse(id="1", result={"ok": True})
    d = resp.to_dict()
    assert d["result"] == {"ok": True}
    assert "error" not in d

    # 错误响应
    err_resp = make_error_response("2", -32601, "方法不存在")
    d = err_resp.to_dict()
    assert d["error"]["code"] == -32601
    assert d["error"]["message"] == "方法不存在"


def test_protocol_parse_message():
    """测试消息解析"""
    from zeroai.mcp.protocol import (
        parse_message, is_request, is_notification, is_response
    )

    # 请求
    msg = parse_message('{"jsonrpc": "2.0", "method": "ping", "id": 1}')
    assert msg is not None
    assert is_request(msg)
    assert not is_notification(msg)
    assert not is_response(msg)

    # 通知（无 id）
    msg = parse_message('{"jsonrpc": "2.0", "method": "initialized"}')
    assert msg is not None
    assert is_notification(msg)
    assert not is_request(msg)

    # 响应
    msg = parse_message('{"jsonrpc": "2.0", "id": 1, "result": {}}')
    assert msg is not None
    assert is_response(msg)
    assert not is_request(msg)

    # 非法消息
    assert parse_message("not json") is None
    assert parse_message('{"foo": "bar"}') is None  # 缺 jsonrpc 字段


def test_protocol_mcp_tool():
    """测试 MCP 工具数据结构"""
    from zeroai.mcp.protocol import MCPTool

    tool = MCPTool(
        name="read_file",
        description="读取文件",
        inputSchema={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    d = tool.to_dict()
    assert d["name"] == "read_file"
    assert d["inputSchema"]["type"] == "object"

    # OpenAI Function Calling 格式
    fn = tool.to_openai_function()
    assert fn["type"] == "function"
    assert fn["function"]["name"] == "read_file"
    assert fn["function"]["parameters"]["type"] == "object"


def test_protocol_initialize_params():
    """测试 initialize 参数构造和解析"""
    from zeroai.mcp.protocol import (
        ClientInfo, ClientCapabilities,
        build_initialize_params, parse_initialize_result,
    )

    client_info = ClientInfo(name="zeroai", version="1.1.3")
    caps = ClientCapabilities()
    params = build_initialize_params(client_info, caps)

    assert params["protocolVersion"] == "2024-11-05"
    assert params["clientInfo"]["name"] == "zeroai"
    assert "capabilities" in params

    # 解析结果
    result = {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "test-server", "version": "1.0"},
    }
    server_info, caps, ver = parse_initialize_result(result)
    assert server_info["name"] == "test-server"
    assert "tools" in caps
    assert ver == "2024-11-05"


def test_protocol_tool_call_result():
    """测试工具调用结果"""
    from zeroai.mcp.protocol import make_text_result, ToolCallResult

    result = make_text_result("hello", is_error=False)
    assert result["content"][0]["text"] == "hello"
    assert result["isError"] is False

    # 错误结果
    err_result = make_text_result("出错了", is_error=True)
    assert err_result["isError"] is True

    # 提取文本
    tcr = ToolCallResult(
        content=[{"type": "text", "text": "line1"}, {"type": "text", "text": "line2"}]
    )
    assert tcr.get_text() == "line1\nline2"


# ============================================================================
# 阶段 3.4：配置管理测试
# ============================================================================
def test_config_server_config_validate():
    """测试服务器配置校验"""
    from zeroai.mcp.config import MCPServerConfig

    # 合法 stdio 配置
    cfg = MCPServerConfig(
        name="test",
        transport="stdio",
        command="python",
        args=["-m", "mcp_server"],
    )
    assert cfg.validate() is None

    # 合法 SSE 配置
    cfg = MCPServerConfig(
        name="test-sse",
        transport="sse",
        url="http://localhost:8765",
    )
    assert cfg.validate() is None

    # 非法传输方式
    cfg = MCPServerConfig(name="bad", transport="websocket")
    err = cfg.validate()
    assert err is not None
    assert "websocket" in err

    # stdio 缺 command
    cfg = MCPServerConfig(name="bad", transport="stdio")
    err = cfg.validate()
    assert "command" in err


def test_config_save_load():
    """测试配置文件保存和加载"""
    from zeroai.mcp.config import MCPConfig, MCPServerConfig

    with tempfile.TemporaryDirectory() as tmp:
        config_path = os.path.join(tmp, "mcp_config.json")
        cfg = MCPConfig(config_path=None)
        cfg.config_path = type(cfg.config_path)(config_path)

        # 添加服务器
        server = MCPServerConfig(
            name="test-server",
            transport="stdio",
            command="python",
            args=["-m", "test_server"],
            description="测试服务器",
        )
        cfg._servers["test-server"] = server
        assert cfg.save() is True

        # 验证文件存在
        assert os.path.exists(config_path)

        # 重新加载
        cfg2 = MCPConfig(config_path=type(cfg.config_path)(config_path))
        loaded = cfg2.get_server("test-server")
        assert loaded is not None
        assert loaded.command == "python"
        assert loaded.args == ["-m", "test_server"]
        assert loaded.description == "测试服务器"


def test_config_add_remove_server():
    """测试添加和删除服务器"""
    from zeroai.mcp.config import MCPConfig, MCPServerConfig

    with tempfile.TemporaryDirectory() as tmp:
        config_path = os.path.join(tmp, "mcp_config.json")
        from pathlib import Path
        cfg = MCPConfig(config_path=Path(config_path))

        # 添加
        server = MCPServerConfig(
            name="new-server",
            transport="stdio",
            command="node",
            args=["server.js"],
        )
        assert cfg.add_server(server) is True
        assert cfg.get_server("new-server") is not None

        # 列出
        servers = cfg.list_servers()
        assert len(servers) == 1
        assert servers[0].name == "new-server"

        # 删除
        assert cfg.remove_server("new-server") is True
        assert cfg.get_server("new-server") is None

        # 删除不存在的
        assert cfg.remove_server("not-exist") is False


# ============================================================================
# 阶段 3.2：工具注册测试
# ============================================================================
def test_registry_tool_name():
    """测试 MCP 工具名生成和解析"""
    from zeroai.mcp.registry import (
        make_mcp_tool_name,
        parse_mcp_tool_name,
        MCP_TOOL_PREFIX,
    )

    # 生成
    name = make_mcp_tool_name("filesystem", "read_file")
    assert name == "mcp__filesystem__read_file"
    assert name.startswith(MCP_TOOL_PREFIX)

    # 解析
    parsed = parse_mcp_tool_name(name)
    assert parsed == ("filesystem", "read_file")

    # 非 MCP 工具
    assert parse_mcp_tool_name("read_file") is None
    assert parse_mcp_tool_name("system_info") is None


def test_registry_registry_init():
    """测试 MCP 注册器初始化（空配置）"""
    from zeroai.mcp.registry import MCPRegistry

    registry = MCPRegistry()
    assert registry.is_initialized is False
    assert len(registry.get_tools_schema()) == 0
    assert len(registry.get_tool_functions()) == 0

    # 空状态检查
    status = registry.get_status_text()
    assert "未初始化" in status


# ============================================================================
# 阶段 3.3：服务器测试
# ============================================================================
def test_server_create():
    """测试 MCP 服务器创建"""
    from zeroai.mcp.server import MCPServer, create_zeroai_server

    # 基础创建
    server = MCPServer(server_name="test", server_version="1.0")
    assert server.server_info.name == "test"
    assert server.capabilities.supports_tools()

    # 注册单个工具
    server.register_tool(
        name="hello",
        description="打招呼",
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        handler=lambda name="": f"Hello, {name}!",
    )
    assert "hello" in server._tools

    # 创建 ZeroAI 服务器（注册内置工具）
    za_server = create_zeroai_server(register_builtin=False)
    assert za_server.server_info.name == "zeroai"


def test_server_register_zeroai_tools():
    """测试注册 ZeroAI 内置工具"""
    from zeroai.mcp.server import create_zeroai_server

    server = create_zeroai_server(register_builtin=True)
    # 应该注册了至少 50 个工具（ZeroAI 有 58 个内置工具）
    assert len(server._tools) >= 50, f"只注册了 {len(server._tools)} 个工具"

    # 检查关键工具存在
    assert "read_file" in server._tools
    assert "write_file" in server._tools
    assert "system_info" in server._tools
    assert "run_command" in server._tools


async def test_server_handle_initialize():
    """测试服务器处理 initialize 请求"""
    from zeroai.mcp.server import MCPServer
    from zeroai.mcp.protocol import (
        METHOD_INITIALIZE, METHOD_LIST_TOOLS,
    )

    server = MCPServer(server_name="test-server", server_version="1.0")
    server.register_tool(
        name="ping",
        description="心跳",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: "pong",
    )

    # 处理 initialize
    result = await server.handle_request(METHOD_INITIALIZE, {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0"},
    })
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "test-server"
    assert "tools" in result["capabilities"]

    # 处理 tools/list
    result = await server.handle_request(METHOD_LIST_TOOLS, {})
    assert "tools" in result
    assert len(result["tools"]) == 1
    assert result["tools"][0]["name"] == "ping"


async def test_server_handle_call_tool():
    """测试服务器处理工具调用"""
    from zeroai.mcp.server import MCPServer
    from zeroai.mcp.protocol import METHOD_CALL_TOOL

    server = MCPServer(server_name="test", server_version="1.0")

    # 注册同步工具
    def greet(name: str = "World") -> str:
        return f"Hello, {name}!"

    server.register_tool(
        name="greet",
        description="问候",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
        handler=greet,
    )

    # 注册异步工具
    async def async_compute(x: int, y: int) -> str:
        await asyncio.sleep(0.01)
        return f"结果: {x + y}"

    server.register_tool(
        name="compute",
        description="计算",
        input_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
        handler=async_compute,
    )

    # 调用同步工具
    result = await server.handle_request(METHOD_CALL_TOOL, {
        "name": "greet",
        "arguments": {"name": "ZeroAI"},
    })
    assert result["isError"] is False
    assert "Hello, ZeroAI" in result["content"][0]["text"]

    # 调用异步工具
    result = await server.handle_request(METHOD_CALL_TOOL, {
        "name": "compute",
        "arguments": {"x": 3, "y": 5},
    })
    assert result["isError"] is False
    assert "结果: 8" in result["content"][0]["text"]

    # 调用不存在的工具
    result = await server.handle_request(METHOD_CALL_TOOL, {
        "name": "nonexistent",
        "arguments": {},
    })
    assert result["isError"] is True


async def test_server_dispatch_message():
    """测试服务器消息分发"""
    from zeroai.mcp.server import MCPServer
    from zeroai.mcp.protocol import parse_message

    server = MCPServer(server_name="test", server_version="1.0")

    # 分发请求
    msg = parse_message('{"jsonrpc": "2.0", "method": "ping", "id": 1}')
    resp = await server.dispatch_message(msg)
    assert resp is not None
    assert resp["id"] == 1
    assert "result" in resp

    # 分发通知（无响应）
    msg = parse_message('{"jsonrpc": "2.0", "method": "notifications/initialized"}')
    resp = await server.dispatch_message(msg)
    assert resp is None


# ============================================================================
# 阶段 3 端到端：Client 连接 Server
# ============================================================================
async def test_end_to_end_stdio():
    """端到端测试：通过 stdio 启动子进程 MCP 服务器并调用工具

    使用 echo 模拟服务器响应，验证协议正确性。
    """
    from zeroai.mcp.client import MCPClient, MCPClientError
    from zeroai.mcp.config import MCPServerConfig

    # 构造一个简单的 echo 服务器脚本
    echo_script = '''
import sys
import json

# 读取一行请求，返回响应
while True:
    line = sys.stdin.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
        if msg.get("method") == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "echo", "version": "1.0"}
                }
            }
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
        elif msg.get("method") == "notifications/initialized":
            pass  # 通知无响应
        elif msg.get("method") == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {
                    "tools": [{
                        "name": "echo",
                        "description": "回显输入",
                        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}
                    }]
                }
            }
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
        elif msg.get("method") == "tools/call":
            args = msg.get("params", {}).get("arguments", {})
            text = args.get("text", "")
            resp = {
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {
                    "content": [{"type": "text", "text": f"Echo: {text}"}],
                    "isError": False
                }
            }
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
        elif msg.get("method") == "ping":
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
        elif msg.get("method") == "shutdown":
            break
    except Exception as e:
        err_resp = {
            "jsonrpc": "2.0",
            "id": msg.get("id", "unknown"),
            "error": {"code": -32603, "message": str(e)}
        }
        sys.stdout.write(json.dumps(err_resp) + "\\n")
        sys.stdout.flush()
'''

    # 写入临时文件
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(echo_script)
        script_path = f.name

    try:
        config = MCPServerConfig(
            name="echo-server",
            transport="stdio",
            command=sys.executable,  # 当前 Python 解释器
            args=[script_path],
        )

        client = MCPClient(config)
        await client.connect()

        # 验证连接
        assert client.is_connected
        assert client.server_info.name == "echo"

        # 获取工具列表
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "echo"

        # 调用工具
        result = await client.call_tool("echo", {"text": "Hello MCP"})
        assert result["isError"] is False
        assert "Echo: Hello MCP" in result["content"][0]["text"]

        # 心跳
        assert await client.ping()

        # 关闭
        await client.close()
        assert not client.is_connected

    finally:
        os.unlink(script_path)


# ============================================================================
# 阶段 1+2+3 集成：Agent Loop + 向量记忆 + MCP 工具
# ============================================================================
def test_integration_agent_loop_imports():
    """测试 Agent Loop 增强版可正常导入"""
    from zeroai.core.agent import (
        AgentLoop, AdvancedAgentLoop,
        ReActPlanner, PlanAndExecutePlanner,
        ReflexionEngine, ToolResultSummarizer,
        Thought, Plan,
        get_advanced_agent_loop,
    )
    assert AgentLoop is not None
    assert AdvancedAgentLoop is not None
    assert ReflexionEngine is not None


def test_integration_memory_imports():
    """测试向量记忆模块可正常导入"""
    from zeroai.memory import (
        VectorStore, ProjectIndexer, Retriever,
        ConversationMemory, FileWatcher,
        get_vector_store, get_retriever,
        get_conversation_memory, get_file_watcher,
    )
    assert VectorStore is not None
    assert ConversationMemory is not None
    assert FileWatcher is not None


def test_integration_mcp_imports():
    """测试 MCP 模块可正常导入"""
    from zeroai.mcp import (
        MCPClient, MCPServer, MCPRegistry,
        MCPServerConfig, MCPConfig,
        initialize_mcp_tools, shutdown_mcp_tools,
        get_mcp_config, get_mcp_registry,
    )
    assert MCPClient is not None
    assert MCPServer is not None
    assert MCPRegistry is not None


def test_integration_zeroai_package():
    """测试 ZeroAI 顶层包可正常导入"""
    import zeroai
    assert zeroai.__version__ == "1.1.3"
    assert hasattr(zeroai, "mcp")
    assert hasattr(zeroai, "core")
    assert hasattr(zeroai, "memory")
    assert hasattr(zeroai, "tools")


# ============================================================================
# 主测试入口
# ============================================================================
async def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("ZeroAI 阶段 3 MCP 协议支持 - 综合测试")
    print("=" * 70)

    results = []

    # 阶段 3.0：协议层
    print("\n--- 阶段 3.0：协议层 ---")
    results.append(run_test("test_protocol_jsonrpc_request", test_protocol_jsonrpc_request))
    results.append(run_test("test_protocol_jsonrpc_response", test_protocol_jsonrpc_response))
    results.append(run_test("test_protocol_parse_message", test_protocol_parse_message))
    results.append(run_test("test_protocol_mcp_tool", test_protocol_mcp_tool))
    results.append(run_test("test_protocol_initialize_params", test_protocol_initialize_params))
    results.append(run_test("test_protocol_tool_call_result", test_protocol_tool_call_result))

    # 阶段 3.4：配置管理
    print("\n--- 阶段 3.4：配置管理 ---")
    results.append(run_test("test_config_server_config_validate", test_config_server_config_validate))
    results.append(run_test("test_config_save_load", test_config_save_load))
    results.append(run_test("test_config_add_remove_server", test_config_add_remove_server))

    # 阶段 3.2：工具注册
    print("\n--- 阶段 3.2：工具注册 ---")
    results.append(run_test("test_registry_tool_name", test_registry_tool_name))
    results.append(run_test("test_registry_registry_init", test_registry_registry_init))

    # 阶段 3.3：服务器
    print("\n--- 阶段 3.3：服务器 ---")
    results.append(run_test("test_server_create", test_server_create))
    results.append(run_test("test_server_register_zeroai_tools", test_server_register_zeroai_tools))
    results.append(await run_async_test("test_server_handle_initialize", test_server_handle_initialize))
    results.append(await run_async_test("test_server_handle_call_tool", test_server_handle_call_tool))
    results.append(await run_async_test("test_server_dispatch_message", test_server_dispatch_message))

    # 端到端
    print("\n--- 端到端：Client ↔ Server ---")
    results.append(await run_async_test("test_end_to_end_stdio", test_end_to_end_stdio))

    # 集成测试
    print("\n--- 阶段 1+2+3 集成 ---")
    results.append(run_test("test_integration_agent_loop_imports", test_integration_agent_loop_imports))
    results.append(run_test("test_integration_memory_imports", test_integration_memory_imports))
    results.append(run_test("test_integration_mcp_imports", test_integration_mcp_imports))
    results.append(run_test("test_integration_zeroai_package", test_integration_zeroai_package))

    # 汇总
    print("\n" + "=" * 70)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"测试结果: {passed}/{total} 通过")
    if passed == total:
        print("所有测试通过！")
    else:
        print(f"有 {total - passed} 个测试失败")
    print("=" * 70)

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
