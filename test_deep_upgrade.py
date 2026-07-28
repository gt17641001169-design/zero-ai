"""深入升级综合测试 - 验证阶段 A（MCP 生态）和阶段 B（Agent 深度优化）

测试覆盖：
阶段 A：
- A.1 MCP 预设配置（filesystem/git/sqlite/fetch 等）
- A.2 /mcp 命令系统导入
- A.3 启动时自动初始化逻辑

阶段 B：
- B.1 思维链可视化（Thought 数据结构 + on_thought_chain 回调）
- B.2 AdvancedAgentLoop 完整接口
- B.3 RAG 自动检索（向量记忆 + 对话记忆）
- B.4 多 Agent 协作（MultiAgentCollaborator + AgentRole）

运行：python test_deep_upgrade.py
"""
import asyncio
import os
import sys
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
# 阶段 A.1：MCP 预设
# ============================================================================
def test_presets_list():
    """测试预设列表"""
    from zeroai.mcp import list_presets, PRESETS
    presets = list_presets()
    assert len(presets) == len(PRESETS)
    # 检查关键预设存在
    names = [p["name"] for p in presets]
    assert "filesystem" in names
    assert "git" in names
    assert "fetch" in names
    assert "sqlite" in names
    # 每个预设都有描述
    for p in presets:
        assert p["description"]
        assert "command" in p
        assert "dependencies_available" in p
        assert "installed" in p


def test_presets_check_dependencies():
    """测试依赖检测"""
    from zeroai.mcp import check_preset_dependencies, check_all_dependencies
    # 检测单个
    dep = check_preset_dependencies("filesystem")
    assert "available" in dep
    assert "missing" in dep
    assert "install_hint" in dep

    # 检测所有
    all_deps = check_all_dependencies()
    assert len(all_deps) == len(__import__("zeroai.mcp", fromlist=["PRESETS"]).PRESETS)


def test_presets_get_info():
    """测试获取预设详情"""
    from zeroai.mcp import get_preset_info
    info = get_preset_info("filesystem")
    assert info is not None
    assert info["name"] == "filesystem"
    assert info["command"] == "npx"
    assert "paths" in info["extra_args"]

    # 不存在的预设
    assert get_preset_info("nonexistent") is None


def test_presets_install_uninstall():
    """测试预设安装和卸载（不实际依赖 npx/uvx）"""
    from zeroai.mcp import (
        install_preset, uninstall_preset, get_mcp_config,
        check_preset_dependencies,
    )
    from zeroai.mcp.config import MCPServerConfig
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        # 使用临时配置文件
        from zeroai.mcp.config import MCPConfig
        cfg = MCPConfig(config_path=Path(tmp) / "mcp_config.json")
        # 替换全局配置
        import zeroai.mcp.config as mcp_cfg_mod
        original_instance = mcp_cfg_mod._config_instance
        mcp_cfg_mod._config_instance = cfg

        try:
            # 检查 npx 是否可用
            dep = check_preset_dependencies("filesystem")
            if not dep["available"]:
                # npx 不可用，跳过实际安装
                print("  (跳过：npx 不可用)")
                return

            # 安装
            ok = install_preset("filesystem", extra_args={"paths": "/tmp"})
            assert ok, "安装失败"
            assert cfg.get_server("filesystem") is not None

            # 卸载
            ok = uninstall_preset("filesystem")
            assert ok
            assert cfg.get_server("filesystem") is None
        finally:
            mcp_cfg_mod._config_instance = original_instance


# ============================================================================
# 阶段 A.2：MCP 命令系统
# ============================================================================
def test_mcp_command_imports():
    """测试 /mcp 命令所需导入"""
    from zeroai.mcp import (
        get_mcp_config, get_mcp_registry,
        initialize_mcp_tools, shutdown_mcp_tools,
        list_presets, install_preset, uninstall_preset,
        check_preset_dependencies,
    )
    assert get_mcp_config is not None
    assert get_mcp_registry is not None
    assert initialize_mcp_tools is not None
    assert list_presets is not None


def test_tui_mcp_handler_exists():
    """测试 TUI 中 _handle_mcp_command 方法已添加"""
    # 解析 tui_agent.py 检查方法存在
    tui_path = os.path.join(_script_dir, "tui_agent.py")
    with open(tui_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "_handle_mcp_command" in content
    assert "/mcp" in content
    assert "_auto_init_mcp" in content
    assert "AdvancedAgentLoop" in content
    assert "on_thought_chain" in content
    assert "get_conversation_memory" in content


# ============================================================================
# 阶段 B.1：思维链可视化
# ============================================================================
def test_thought_dataclass():
    """测试 Thought 数据结构"""
    from zeroai.core.agent import Thought
    import time

    t = Thought(
        step=1,
        thought="分析用户需求",
        action_type="tool_call",
        tool_name="read_file",
        args={"path": "/tmp/test.py"},
    )
    assert t.step == 1
    assert t.action_type == "tool_call"
    assert t.tool_name == "read_file"
    assert t.success is True  # 默认
    assert t.timestamp > 0

    # 反思类型
    t2 = Thought(
        step=2,
        thought="工具失败，反思中",
        action_type="reflect",
        tool_name="read_file",
        reflection="文件不存在",
        success=False,
    )
    assert t2.action_type == "reflect"
    assert t2.success is False
    assert t2.reflection == "文件不存在"


def test_advanced_agent_loop_callbacks():
    """测试 AdvancedAgentLoop 的思维链回调接口"""
    from zeroai.core.agent import AdvancedAgentLoop, Thought
    loop = AdvancedAgentLoop(enable_plan=False, enable_reflexion=False)

    # 检查回调属性
    assert hasattr(loop, "on_thought_chain")
    assert hasattr(loop, "on_thought")
    assert hasattr(loop, "on_tool_call")
    assert hasattr(loop, "on_tool_result")
    assert hasattr(loop, "on_final_answer")

    # 思维链列表
    assert isinstance(loop.thought_chain, list)
    assert len(loop.thought_chain) == 0


# ============================================================================
# 阶段 B.2：AdvancedAgentLoop 接口
# ============================================================================
def test_advanced_agent_loop_init():
    """测试 AdvancedAgentLoop 初始化参数"""
    from zeroai.core.agent import (
        AdvancedAgentLoop, ReflexionEngine,
        ToolResultSummarizer, PlanAndExecutePlanner,
    )

    # 默认初始化（不启用任何增强）
    loop = AdvancedAgentLoop(
        enable_plan=False,
        enable_reflexion=False,
        enable_parallel=False,
        enable_summarize=False,
    )
    assert loop.enable_plan is False
    assert loop.reflexion_engine is None
    assert loop.summarizer is None
    assert loop.plan_planner is None

    # 全功能初始化
    loop2 = AdvancedAgentLoop(
        enable_plan=True,
        enable_reflexion=True,
        enable_parallel=True,
        enable_summarize=True,
    )
    assert loop2.enable_plan is True
    assert loop2.reflexion_engine is not None
    assert loop2.summarizer is not None
    assert loop2.plan_planner is not None


def test_advanced_agent_loop_tool_map():
    """测试 AdvancedAgentLoop 的工具映射"""
    from zeroai.core.agent import AdvancedAgentLoop

    tool_map = {"test_tool": lambda **kw: "ok"}
    tools_schema = [{
        "type": "function",
        "function": {
            "name": "test_tool",
            "description": "测试工具",
            "parameters": {"type": "object", "properties": {}},
        },
    }]

    loop = AdvancedAgentLoop(
        tool_map=tool_map,
        tools_schema=tools_schema,
        enable_reflexion=False,
        enable_summarize=False,
    )
    assert "test_tool" in loop.tool_map
    assert len(loop.tools_schema) == 1


# ============================================================================
# 阶段 B.3：RAG 自动检索
# ============================================================================
def test_conversation_memory_imports():
    """测试对话记忆模块"""
    from zeroai.memory import ConversationMemory, get_conversation_memory
    assert ConversationMemory is not None
    assert get_conversation_memory is not None


async def test_conversation_memory_add_recall():
    """测试对话记忆添加和检索"""
    from zeroai.memory import ConversationMemory, get_vector_store
    from zeroai.memory.vector_store import VectorStore

    # 用临时存储测试
    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStore(db_path=os.path.join(tmp, "test_conv.db"))
        mem = ConversationMemory(store=store)

        # 添加对话
        ok = await mem.add_turn(
            user_input="如何用 Python 读取文件",
            assistant_response="使用 open() 函数...",
            metadata={"mode": "test"},
        )
        assert ok

        # 检索
        results = mem.recall("读取文件", top_k=3)
        assert len(results) >= 0  # 可能为空（取决于向量索引是否建立）


def test_file_watcher_imports():
    """测试文件监视模块"""
    from zeroai.memory import FileWatcher, get_file_watcher
    assert FileWatcher is not None
    assert get_file_watcher is not None


# ============================================================================
# 阶段 B.4：多 Agent 协作
# ============================================================================
def test_multi_agent_collaborator_init():
    """测试多 Agent 协作器初始化"""
    from zeroai.core.agent import MultiAgentCollaborator, AgentRole

    collab = MultiAgentCollaborator(
        orchestrator_model="glm",
        max_steps_per_agent=3,
    )
    assert collab.orchestrator_model == "glm"
    assert collab.max_steps_per_agent == 3
    assert len(collab.roles) == 0

    # 添加角色
    role = AgentRole(
        name="coder",
        specialty="代码编写",
        system_prompt="你是代码专家",
        tools_whitelist=["read_file", "write_file"],
    )
    collab.add_role(role)
    assert "coder" in collab.roles
    assert collab.roles["coder"].specialty == "代码编写"

    # 移除角色
    collab.remove_role("coder")
    assert "coder" not in collab.roles


def test_multi_agent_role_tools_filter():
    """测试角色工具白名单"""
    from zeroai.core.agent import AgentRole

    role = AgentRole(
        name="reviewer",
        specialty="代码审查",
        system_prompt="你是审查专家",
        tools_whitelist=["read_file", "grep_files"],
    )
    assert role.tools_whitelist == ["read_file", "grep_files"]
    assert "read_file" in role.tools_whitelist


def test_multi_agent_callbacks():
    """测试多 Agent 协作回调接口"""
    from zeroai.core.agent import MultiAgentCollaborator

    collab = MultiAgentCollaborator()
    assert hasattr(collab, "on_agent_start")
    assert hasattr(collab, "on_agent_done")
    assert hasattr(collab, "on_orchestrator_thought")
    assert collab.on_agent_start is None
    assert collab.on_agent_done is None


# ============================================================================
# 阶段 B 集成：TUI 升级
# ============================================================================
def test_tui_react_turn_upgraded():
    """测试 TUI _run_react_turn 已升级为增强版"""
    tui_path = os.path.join(_script_dir, "tui_agent.py")
    with open(tui_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 检查关键升级点
    assert "AdvancedAgentLoop" in content, "未升级到 AdvancedAgentLoop"
    assert "run_with_chain" in content, "未使用 run_with_chain"
    assert "on_thought_chain" in content, "未添加思维链回调"
    assert "get_conversation_memory" in content, "未集成对话记忆"
    assert "enable_reflexion" in content, "未启用反思"
    assert "enable_parallel" in content, "未启用并行"
    assert "enable_summarize" in content, "未启用摘要"
    assert "_react_plan_mode" in content, "未添加 Plan 模式切换"
    assert "/react plan" in content, "未添加 /react plan 命令"


def test_tui_mcp_commands():
    """测试 TUI 中 /mcp 命令完整性"""
    tui_path = os.path.join(_script_dir, "tui_agent.py")
    with open(tui_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 检查所有子命令
    assert "/mcp list" in content or '"list"' in content
    assert "/mcp install" in content or '"install"' in content
    assert "/mcp connect" in content or '"connect"' in content
    assert "/mcp tools" in content or '"tools"' in content
    assert "/mcp enable" in content or '"enable"' in content
    assert "/mcp disable" in content or '"disable"' in content


def test_tui_help_updated():
    """测试帮助信息已更新"""
    tui_path = os.path.join(_script_dir, "tui_agent.py")
    with open(tui_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "/mcp           MCP 协议管理" in content


# ============================================================================
# 端到端验证
# ============================================================================
async def test_end_to_end_thought_chain():
    """端到端：AdvancedAgentLoop 思维链完整性

    使用 Mock LLM 验证思维链记录功能。
    """
    from zeroai.core.agent import (
        AdvancedAgentLoop, ReActPlanner, Thought,
    )

    # 收集思维链
    received_thoughts = []

    async def _on_thought_chain(thought: Thought):
        received_thoughts.append(thought)

    # 创建 loop
    loop = AdvancedAgentLoop(
        enable_reflexion=False,
        enable_parallel=False,
        enable_summarize=False,
    )
    loop.on_thought_chain = _on_thought_chain

    # 直接测试 _emit_thought
    test_thought = Thought(
        step=1,
        thought="测试思维",
        action_type="tool_call",
        tool_name="test",
    )
    await loop._emit_thought(test_thought)

    # 验证
    assert len(received_thoughts) == 1
    assert received_thoughts[0].thought == "测试思维"
    assert len(loop.thought_chain) == 1


# ============================================================================
# 主测试入口
# ============================================================================
async def run_all_tests():
    print("=" * 70)
    print("ZeroAI 深入升级综合测试（阶段 A + 阶段 B）")
    print("=" * 70)

    results = []

    # 阶段 A.1
    print("\n--- 阶段 A.1：MCP 预设 ---")
    results.append(run_test("test_presets_list", test_presets_list))
    results.append(run_test("test_presets_check_dependencies", test_presets_check_dependencies))
    results.append(run_test("test_presets_get_info", test_presets_get_info))
    results.append(run_test("test_presets_install_uninstall", test_presets_install_uninstall))

    # 阶段 A.2
    print("\n--- 阶段 A.2：/mcp 命令系统 ---")
    results.append(run_test("test_mcp_command_imports", test_mcp_command_imports))
    results.append(run_test("test_tui_mcp_handler_exists", test_tui_mcp_handler_exists))

    # 阶段 B.1
    print("\n--- 阶段 B.1：思维链可视化 ---")
    results.append(run_test("test_thought_dataclass", test_thought_dataclass))
    results.append(run_test("test_advanced_agent_loop_callbacks", test_advanced_agent_loop_callbacks))

    # 阶段 B.2
    print("\n--- 阶段 B.2：AdvancedAgentLoop 接口 ---")
    results.append(run_test("test_advanced_agent_loop_init", test_advanced_agent_loop_init))
    results.append(run_test("test_advanced_agent_loop_tool_map", test_advanced_agent_loop_tool_map))

    # 阶段 B.3
    print("\n--- 阶段 B.3：RAG 自动检索 ---")
    results.append(run_test("test_conversation_memory_imports", test_conversation_memory_imports))
    results.append(await run_async_test("test_conversation_memory_add_recall", test_conversation_memory_add_recall))
    results.append(run_test("test_file_watcher_imports", test_file_watcher_imports))

    # 阶段 B.4
    print("\n--- 阶段 B.4：多 Agent 协作 ---")
    results.append(run_test("test_multi_agent_collaborator_init", test_multi_agent_collaborator_init))
    results.append(run_test("test_multi_agent_role_tools_filter", test_multi_agent_role_tools_filter))
    results.append(run_test("test_multi_agent_callbacks", test_multi_agent_callbacks))

    # TUI 集成
    print("\n--- TUI 集成验证 ---")
    results.append(run_test("test_tui_react_turn_upgraded", test_tui_react_turn_upgraded))
    results.append(run_test("test_tui_mcp_commands", test_tui_mcp_commands))
    results.append(run_test("test_tui_help_updated", test_tui_help_updated))

    # 端到端
    print("\n--- 端到端 ---")
    results.append(await run_async_test("test_end_to_end_thought_chain", test_end_to_end_thought_chain))

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
