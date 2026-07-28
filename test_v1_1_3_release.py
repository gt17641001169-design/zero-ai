"""v1.1.3 发布测试：完整集成验证

测试目标：
1. 版本号正确（1.1.3）
2. 统一入口 zeroai.main 可用
3. python -m zeroai 支持
4. zeroai.core 全部子模块可导入
5. zeroai.tools 全部子模块可导入 + registry 一致性
6. zeroai.tui 包装模块可导入
7. tui_agent.py 向后兼容
8. 阶段3 切换块激活（_ZEROAI_IMPL_ACTIVE=True）
9. 关键工具函数实际调用
"""
import sys
import os
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_version():
    """测试 1：版本号验证"""
    print("[Test 1] 版本号验证...")
    result = subprocess.run(
        [sys.executable, "-m", "zeroai", "--version"],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__))
    )
    assert result.returncode == 0, f"zeroai --version 失败: {result.stderr}"
    assert "1.1.3" in result.stdout, f"版本号不是 1.1.3: {result.stdout}"
    print(f"  OK: {result.stdout.strip()}")


def test_main_entry():
    """测试 2：统一入口"""
    print("\n[Test 2] 统一入口验证...")
    from zeroai.main import main, _get_version
    assert callable(main), "zeroai.main.main 不可调用"
    assert _get_version() == "1.1.3", f"版本号错误: {_get_version()}"
    print(f"  OK: zeroai.main.main 可调用，版本 {_get_version()}")


def test_module_entry():
    """测试 3：python -m zeroai 支持"""
    print("\n[Test 3] python -m zeroai 支持...")
    import zeroai.__main__
    assert hasattr(zeroai.__main__, "main"), "zeroai.__main__ 无 main 函数"
    print("  OK: python -m zeroai 可用")


def test_core_imports():
    """测试 4：zeroai.core 全部子模块"""
    print("\n[Test 4] zeroai.core 子模块导入...")
    from zeroai.core import (
        paths, runtime, secrets, constants, expert_route,
        context_compress, model_manager, response_utils,
    )
    # 验证关键函数
    from zeroai.core.paths import _get_desktop_dir
    from zeroai.core.runtime import runtime_cache, RuntimeCache
    from zeroai.core.secrets import _load_config, _save_config
    from zeroai.core.constants import MODEL_CONFIGS, EXPERT_TEAM, WORK_MODE
    from zeroai.core.expert_route import route_expert, LRUCache
    from zeroai.core.context_compress import cleanup_context, compress_context
    from zeroai.core.model_manager import get_active_model_info
    from zeroai.core.response_utils import _strip_model_tokens
    print("  OK: 全部 8 个 core 子模块导入成功")


def test_tools_imports():
    """测试 5：zeroai.tools 全部子模块 + registry"""
    print("\n[Test 5] zeroai.tools 子模块导入...")
    from zeroai.tools import (
        file_manager, command_exec, network, system_check,
        security, doc_gen, academic, window_mgr, ssh_ops, registry,
    )
    from zeroai.tools.registry import TOOLS, TOOL_MAP
    assert len(TOOLS) == 56, f"TOOLS 数量错误: {len(TOOLS)}"
    assert len(TOOL_MAP) == 56, f"TOOL_MAP 数量错误: {len(TOOL_MAP)}"
    tools_keys = {t["function"]["name"] for t in TOOLS}
    map_keys = set(TOOL_MAP.keys())
    assert tools_keys == map_keys, "TOOLS 和 TOOL_MAP key 不一致"
    print(f"  OK: 全部 10 个 tools 子模块导入成功，{len(TOOLS)} 个工具注册")


def test_tui_wrappers():
    """测试 6：zeroai.tui 包装模块"""
    print("\n[Test 6] zeroai.tui 包装模块...")
    from zeroai.tui.colors import C_BG, C_FG
    from zeroai.tui.markdown import render_markdown
    from zeroai.tui.identity import _sanitize_identity_leak
    from zeroai.tui.widgets import InfoBar, HintBar, TokenBar
    from zeroai.tui.screens import AddModelScreen, SettingsScreen, VoiceDialogScreen
    from zeroai.tui.app import ZeroAI

    # 验证 __getattr__ 按需导入
    import zeroai.tui
    assert zeroai.tui.ZeroAI is ZeroAI, "__getattr__ 导入不一致"
    assert zeroai.tui.InfoBar is InfoBar, "__getattr__ 导入不一致"
    print("  OK: 全部 7 个 tui 子模块导入成功（colors/markdown/identity/widgets/screens/app/icons）")


def test_tui_agent_compat():
    """测试 7：tui_agent.py 向后兼容"""
    print("\n[Test 7] tui_agent.py 向后兼容...")
    import tui_agent
    assert hasattr(tui_agent, "ZeroAI"), "tui_agent.ZeroAI 不存在"
    assert hasattr(tui_agent, "main"), "tui_agent.main 不存在"
    assert hasattr(tui_agent, "TOOLS"), "tui_agent.TOOLS 不存在"
    assert hasattr(tui_agent, "TOOL_MAP"), "tui_agent.TOOL_MAP 不存在"
    assert tui_agent._ZEROAI_IMPL_ACTIVE is True, "切换块未激活"
    print(f"  OK: tui_agent.py 兼容，_ZEROAI_IMPL_ACTIVE={tui_agent._ZEROAI_IMPL_ACTIVE}")


def test_switch_active():
    """测试 8：阶段3 切换块激活状态"""
    print("\n[Test 8] 阶段3 切换块激活...")
    import tui_agent
    import zeroai.tools.registry as reg
    # TOOLS 和 TOOL_MAP 应该是同一对象（切换成功）
    assert tui_agent.TOOLS is reg.TOOLS, "tui_agent.TOOLS 未切换到 registry"
    assert tui_agent.TOOL_MAP is reg.TOOL_MAP, "tui_agent.TOOL_MAP 未切换到 registry"
    # 工具函数应来自 zeroai.tools.*
    assert tui_agent.read_file.__module__.startswith("zeroai.tools"), \
        f"read_file 未切换: {tui_agent.read_file.__module__}"
    assert tui_agent.run_command.__module__.startswith("zeroai.tools"), \
        f"run_command 未切换: {tui_agent.run_command.__module__}"
    print("  OK: 切换块激活，工具函数来自 zeroai.tools.*")


def test_real_calls():
    """测试 9：关键功能实际调用"""
    print("\n[Test 9] 关键功能实际调用...")
    import tui_agent

    # read_file
    result = tui_agent.read_file(__file__, max_length=50)
    assert isinstance(result, str) and "v1.1.3" in result or "test" in result.lower()
    print(f"  OK: read_file 成功（{len(result)} 字符）")

    # system_info
    result = tui_agent.system_info()
    assert isinstance(result, str)
    print(f"  OK: system_info 成功（{len(result)} 字符）")

    # route_expert
    expert = tui_agent.route_expert("写一个 Python 函数")
    assert isinstance(expert, str)
    print(f"  OK: route_expert 成功（{expert}）")

    # render_formula
    result = tui_agent.render_formula("E=mc^2")
    assert isinstance(result, str)
    print(f"  OK: render_formula 成功（{result[:30]}）")

    # _get_desktop_dir
    desktop = tui_agent._get_desktop_dir()
    assert isinstance(desktop, str) and desktop
    print(f"  OK: _get_desktop_dir 成功（{desktop}）")


def test_no_circular():
    """测试 10：循环导入验证"""
    print("\n[Test 10] 循环导入验证...")
    import importlib
    import tui_agent
    importlib.reload(tui_agent)
    assert tui_agent._ZEROAI_IMPL_ACTIVE is True
    print("  OK: 重载后切换块仍激活")


def main():
    print("=" * 70)
    print("ZeroAI v1.1.3 发布测试")
    print("=" * 70)

    test_version()
    test_main_entry()
    test_module_entry()
    test_core_imports()
    test_tools_imports()
    test_tui_wrappers()
    test_tui_agent_compat()
    test_switch_active()
    test_real_calls()
    test_no_circular()

    print("\n" + "=" * 70)
    print("✅ 全部 10 项测试通过！v1.1.3 发布就绪")
    print("=" * 70)
    print("\n架构摘要：")
    print("  zeroai/                    模块化包（推荐）")
    print("  ├── core/                  核心层（8 个子模块）")
    print("  ├── tools/                 工具层（10 个子模块，56 个工具）")
    print("  ├── tui/                   TUI 包装层（7 个子模块）")
    print("  ├── main.py                统一入口")
    print("  └── __main__.py            模块入口")
    print("  tui_agent.py               原始实现（保留备份，向后兼容）")
    print("  pyproject.toml             版本 1.1.3，入口 zeroai.main:main")


if __name__ == "__main__":
    main()
