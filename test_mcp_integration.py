"""阶段 C：MCP 接入验证测试

验证 ZeroAI MCP Server 的完整接入能力：
- C.1 MCP 服务器预设依赖检测
- C.2 Claude Desktop 配置生成（配置示例）
- C.3 端到端：启动 ZeroAI MCP Server 子进程，用 MCPClient 连接并调用工具
- C.4 工具调用完整性验证（tools/list + tools/call）

运行：python test_mcp_integration.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import tempfile

_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)


def _pass(name):
    print(f"[PASS] {name}")


def _fail(name, err):
    print(f"[FAIL] {name}: {err}")


def run_test(name, fn):
    try:
        fn()
        _pass(name)
        return True
    except Exception as e:
        _fail(name, e)
        return False


async def run_async_test(name, fn):
    try:
        await fn()
        _pass(name)
        return True
    except Exception as e:
        _fail(name, e)
        return False


# ============================================================================
# C.1：MCP 预设依赖检测
# ============================================================================
def test_c1_preset_dependencies():
    """C.1 验证预设依赖检测完整性"""
    from zeroai.mcp import check_all_dependencies, PRESETS

    all_deps = check_all_dependencies()
    # 所有预设都必须有检测结果
    assert len(all_deps) == len(PRESETS)
    for name, dep in all_deps.items():
        assert "available" in dep, f"{name} 缺少 available 字段"
        assert "missing" in dep, f"{name} 缺少 missing 字段"
        assert "install_hint" in dep, f"{name} 缺少 install_hint 字段"
        # 不可用的必须有安装提示
        if not dep["available"]:
            assert dep["install_hint"], f"{name} 不可用但无安装提示"


def test_c1_preset_commands():
    """C.1 验证预设命令格式正确"""
    from zeroai.mcp import PRESETS

    for name, preset in PRESETS.items():
        assert preset["command"] in ("npx", "uvx", "python", "node"), \
            f"{name} 命令异常: {preset['command']}"
        assert isinstance(preset["args"], list), f"{name} args 不是列表"
        assert preset["transport"] in ("stdio", "sse"), \
            f"{name} 传输方式异常: {preset['transport']}"


# ============================================================================
# C.2：Claude Desktop 配置生成
# ============================================================================
def test_c2_claude_desktop_config():
    """C.2 生成 Claude Desktop 配置示例

    Claude Desktop 的 MCP 配置文件位置：
    - macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
    - Windows: %APPDATA%\\Claude\\claude_desktop_config.json
    """
    from zeroai.mcp.presets import PRESETS

    # 生成 ZeroAI 作为 MCP Server 的配置
    zeroai_config = {
        "mcpServers": {
            "zeroai": {
                "command": sys.executable,
                "args": ["-m", "zeroai.mcp"],
                "transport": "stdio",
            }
        }
    }

    # 验证配置格式
    assert "mcpServers" in zeroai_config
    assert "zeroai" in zeroai_config["mcpServers"]
    server = zeroai_config["mcpServers"]["zeroai"]
    assert server["command"] == sys.executable
    assert "-m" in server["args"]
    assert "zeroai.mcp" in server["args"]

    # 验证 JSON 可序列化
    json_str = json.dumps(zeroai_config, indent=2)
    parsed = json.loads(json_str)
    assert parsed == zeroai_config

    # 生成完整配置（含常用预设）
    full_config = {"mcpServers": {"zeroai": server}}

    # 只添加依赖可用的预设
    from zeroai.mcp import check_preset_dependencies
    for name, preset in PRESETS.items():
        dep = check_preset_dependencies(name)
        if dep["available"]:
            full_config["mcpServers"][name] = {
                "command": preset["command"],
                "args": preset["args"],
                "transport": preset["transport"],
            }

    # 验证完整配置
    assert "zeroai" in full_config["mcpServers"]
    json_str = json.dumps(full_config, indent=2, ensure_ascii=False)
    assert len(json_str) > 100  # 有内容


def test_c2_config_save_and_reload():
    """C.2 验证 MCP 配置保存和重载"""
    from zeroai.mcp.config import MCPConfig, MCPServerConfig
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "mcp_config.json"
        cfg = MCPConfig(config_path=config_path)

        # 添加 ZeroAI 自身作为 MCP Server
        server = MCPServerConfig(
            name="zeroai-self",
            transport="stdio",
            command=sys.executable,
            args=["-m", "zeroai.mcp"],
            description="ZeroAI 自身工具集",
        )
        cfg.add_server(server)

        # 重载
        cfg2 = MCPConfig(config_path=config_path)
        loaded = cfg2.get_server("zeroai-self")
        assert loaded is not None
        assert loaded.command == sys.executable
        assert loaded.args == ["-m", "zeroai.mcp"]
        assert loaded.description == "ZeroAI 自身工具集"


# ============================================================================
# C.3：端到端 - 启动 ZeroAI MCP Server 并用 MCPClient 连接
# ============================================================================
async def test_c3_end_to_end_zeroai_mcp_server():
    """C.3 端到端：启动 ZeroAI MCP Server 子进程，用 MCPClient 连接

    流程：
    1. 用 subprocess 启动 `python -m zeroai.mcp` 子进程
    2. 用 MCPClient 通过 stdio 连接
    3. 完成 initialize 握手
    4. 调用 tools/list 验证工具列表
    5. 调用 tools/call 执行 system_info 工具
    6. 关闭连接
    """
    from zeroai.mcp.client import MCPClient, MCPClientError
    from zeroai.mcp.config import MCPServerConfig

    # 构造配置：启动 ZeroAI 自身作为 MCP Server
    config = MCPServerConfig(
        name="zeroai-server",
        transport="stdio",
        command=sys.executable,
        args=["-m", "zeroai.mcp"],
    )

    client = MCPClient(config)

    try:
        # 1. 连接（含 initialize 握手）
        await client.connect()
        assert client.is_connected, "连接失败"

        # 2. 验证服务器信息
        assert client.server_info.name == "zeroai"
        assert client.server_info.version == "1.1.3"

        # 3. 验证服务器能力
        assert client.server_capabilities.supports_tools(), "服务器不支持 tools"

        # 4. 获取工具列表
        tools = await client.list_tools()
        assert len(tools) >= 50, f"工具数不足: {len(tools)}"

        # 验证关键工具存在
        tool_names = [t.name for t in tools]
        assert "read_file" in tool_names, "缺少 read_file"
        assert "write_file" in tool_names, "缺少 write_file"
        assert "system_info" in tool_names, "缺少 system_info"
        assert "run_command" in tool_names, "缺少 run_command"

        # 5. 调用 system_info 工具
        result = await client.call_tool("system_info", {})
        assert isinstance(result, dict)
        assert "content" in result
        content = result["content"]
        assert len(content) > 0
        # 验证返回了文本内容
        text_parts = [
            item.get("text", "") for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        assert len(text_parts) > 0
        assert "错误" not in text_parts[0][:50]  # 前 50 字符不应是错误

        # 6. 心跳检测
        assert await client.ping(), "心跳检测失败"

    finally:
        await client.close()
        assert not client.is_connected


async def test_c3_call_multiple_tools():
    """C.3 端到端：调用多个工具验证稳定性"""
    from zeroai.mcp.client import MCPClient
    from zeroai.mcp.config import MCPServerConfig

    config = MCPServerConfig(
        name="zeroai-multi",
        transport="stdio",
        command=sys.executable,
        args=["-m", "zeroai.mcp"],
    )

    client = MCPClient(config)

    try:
        await client.connect()

        # 调用多个工具
        # 1. system_info
        r1 = await client.call_tool("system_info", {})
        assert r1.get("isError") is False

        # 2. list_dir（列当前目录）
        r2 = await client.call_tool("list_dir", {"path": "."})
        assert r2.get("isError") is False

        # 3. 调用不存在的工具（应返回错误）
        r3 = await client.call_tool("nonexistent_tool", {})
        assert r3.get("isError") is True

    finally:
        await client.close()


# ============================================================================
# C.4：工具调用完整性验证
# ============================================================================
async def test_c4_tool_schema_completeness():
    """C.4 验证所有工具 schema 完整性"""
    from zeroai.mcp.client import MCPClient
    from zeroai.mcp.config import MCPServerConfig

    config = MCPServerConfig(
        name="zeroai-schema",
        transport="stdio",
        command=sys.executable,
        args=["-m", "zeroai.mcp"],
    )

    client = MCPClient(config)

    try:
        await client.connect()
        tools = await client.list_tools()

        for tool in tools:
            # 每个工具必须有 name 和 description
            assert tool.name, f"工具缺少 name: {tool}"
            assert tool.description, f"工具 {tool.name} 缺少 description"

            # inputSchema 必须是 dict 且有 type 字段
            assert isinstance(tool.inputSchema, dict), \
                f"工具 {tool.name} inputSchema 不是 dict"
            assert "type" in tool.inputSchema, \
                f"工具 {tool.name} inputSchema 缺少 type"

            # OpenAI Function 格式转换
            fn = tool.to_openai_function()
            assert fn["type"] == "function"
            assert fn["function"]["name"] == tool.name
            assert fn["function"]["parameters"] == tool.inputSchema

    finally:
        await client.close()


async def test_c4_openai_tools_schema():
    """C.4 验证 OpenAI 工具 schema 格式可直接用于 LLM 调用"""
    from zeroai.mcp.client import MCPClient
    from zeroai.mcp.config import MCPServerConfig

    config = MCPServerConfig(
        name="zeroai-openai",
        transport="stdio",
        command=sys.executable,
        args=["-m", "zeroai.mcp"],
    )

    client = MCPClient(config)

    try:
        await client.connect()
        # 必须先调用 list_tools() 填充缓存，get_openai_tools_schema() 才有数据
        tools = await client.list_tools()
        assert len(tools) >= 50

        schemas = client.get_openai_tools_schema()
        assert len(schemas) >= 50

        for schema in schemas:
            assert schema["type"] == "function"
            fn = schema["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert isinstance(fn["parameters"], dict)

    finally:
        await client.close()


# ============================================================================
# 主测试入口
# ============================================================================
async def run_all_tests():
    print("=" * 70)
    print("ZeroAI 阶段 C：MCP 接入验证测试")
    print("=" * 70)

    results = []

    # C.1
    print("\n--- C.1：预设依赖检测 ---")
    results.append(run_test("test_c1_preset_dependencies", test_c1_preset_dependencies))
    results.append(run_test("test_c1_preset_commands", test_c1_preset_commands))

    # C.2
    print("\n--- C.2：Claude Desktop 配置 ---")
    results.append(run_test("test_c2_claude_desktop_config", test_c2_claude_desktop_config))
    results.append(run_test("test_c2_config_save_and_reload", test_c2_config_save_and_reload))

    # C.3
    print("\n--- C.3：端到端 MCP Server ---")
    results.append(await run_async_test(
        "test_c3_end_to_end_zeroai_mcp_server",
        test_c3_end_to_end_zeroai_mcp_server
    ))
    results.append(await run_async_test(
        "test_c3_call_multiple_tools",
        test_c3_call_multiple_tools
    ))

    # C.4
    print("\n--- C.4：工具完整性 ---")
    results.append(await run_async_test(
        "test_c4_tool_schema_completeness",
        test_c4_tool_schema_completeness
    ))
    results.append(await run_async_test(
        "test_c4_openai_tools_schema",
        test_c4_openai_tools_schema
    ))

    # 汇总
    print("\n" + "=" * 70)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"测试结果: {passed}/{total} 通过")
    if passed == total:
        print("所有测试通过！ZeroAI MCP Server 可被外部客户端（如 Claude Desktop）调用。")
    else:
        print(f"有 {total - passed} 个测试失败")
    print("=" * 70)
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
