"""
ZeroAI Full Integration Test

验证 ZeroAI 核心模块的完整集成：
- zeroai 主包导入
- tui_agent 入口模块
- 专家系统 / LLM / 配置模块
- zeroai_tui C/Zig 加速层（可选，未安装时降级测试）
- MCP / Agent Loop / 向量记忆（阶段 3 新增）

运行：python test_full_integration.py
"""
import sys
import os

# Add paths
sys.path.insert(0, os.path.dirname(__file__))


def test_full_integration():
    """Test complete integration"""
    print("=" * 60)
    print("ZeroAI Full Integration Test")
    print("=" * 60)
    print()

    tests = [
        ("Import zeroai package", test_import_zeroai),
        ("Import tui_agent", test_import_tui_agent),
        ("Expert system ready", test_expert_system),
        ("LLM module ready", test_llm_module),
        ("Config module ready", test_config),
        ("MCP module ready", test_mcp_module),
        ("Agent Loop ready", test_agent_loop),
        ("Vector memory ready", test_vector_memory),
        ("Tools registry ready", test_tools_registry),
        ("ZeroAI-TUI (optional)", test_zeroai_tui_optional),
    ]

    passed = 0
    failed = 0
    skipped = 0

    for name, test_func in tests:
        print(f"[Test] {name}...")
        try:
            result = test_func()
            if result is True:
                print(f"  [OK] Passed")
                passed += 1
            elif result == "skip":
                print(f"  [SKIP] Skipped (optional dependency not installed)")
                skipped += 1
            else:
                print(f"  [FAIL] Failed")
                failed += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)

    if failed == 0:
        print()
        print("Full integration ready!")
        print()
        print("Usage:")
        print("  # Run with Textual UI (default)")
        print("  python tui_agent.py")
        print()
        print("  # Run with zeroai-tui UI (if installed)")
        print("  python tui_agent.py --ui zeroai-tui")
        print()
        print("  # Run ZeroAI as MCP Server")
        print("  python -m zeroai.mcp")

    return failed == 0


def test_import_zeroai():
    """Test importing zeroai package"""
    import zeroai
    return hasattr(zeroai, '__version__')


def test_import_tui_agent():
    """Test importing tui_agent"""
    import tui_agent
    return hasattr(tui_agent, 'main')


def test_expert_system():
    """Test expert system"""
    from zeroai.core.expert import ExpertRouter
    router = ExpertRouter()
    return router is not None


def test_llm_module():
    """Test LLM module"""
    from zeroai.core import llm
    return hasattr(llm, 'LLMClient')


def test_config():
    """Test config module"""
    from zeroai.core.config import Config
    config = Config()
    return config is not None


def test_mcp_module():
    """Test MCP module (阶段 3 新增)"""
    from zeroai import mcp
    return hasattr(mcp, 'MCPClient') and hasattr(mcp, 'MCPServer')


def test_agent_loop():
    """Test Agent Loop (阶段 1 增强)"""
    from zeroai.core.agent import AdvancedAgentLoop, MultiAgentCollaborator
    return AdvancedAgentLoop is not None and MultiAgentCollaborator is not None


def test_vector_memory():
    """Test vector memory (阶段 2 新增)"""
    from zeroai.memory import VectorStore, ConversationMemory
    return VectorStore is not None and ConversationMemory is not None


def test_tools_registry():
    """Test tools registry"""
    from zeroai.tools.registry import TOOL_MAP, TOOLS
    return len(TOOL_MAP) > 0 and len(TOOLS) > 0


def test_zeroai_tui_optional():
    """Test zeroai_tui (optional - skip if not installed)"""
    try:
        import zeroai_tui
        return hasattr(zeroai_tui, '__version__')
    except ImportError:
        return "skip"


if __name__ == "__main__":
    success = test_full_integration()
    sys.exit(0 if success else 1)
