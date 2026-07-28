"""阶段3 回归测试：验证 tui_agent.py 内部调用切换到 zeroai 包

测试目标：
1. tui_agent.py 能正常导入
2. 所有工具函数都来自 zeroai.tools.*
3. core 层函数都来自 zeroai.core.*
4. TOOLS 和 TOOL_MAP 与 registry 中的一致
5. 关键工具函数能正常调用（不触发危险操作）
6. 工具函数签名一致性
"""
import sys
import os
import inspect

# 确保从项目根目录导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_import():
    """测试 1：tui_agent.py 能正常导入"""
    print("[Test 1] 导入 tui_agent.py...")
    import tui_agent
    assert hasattr(tui_agent, "TOOLS"), "tui_agent.TOOLS 不存在"
    assert hasattr(tui_agent, "TOOL_MAP"), "tui_agent.TOOL_MAP 不存在"
    assert hasattr(tui_agent, "_ZEROAI_IMPL_ACTIVE"), "tui_agent._ZEROAI_IMPL_ACTIVE 不存在"
    assert tui_agent._ZEROAI_IMPL_ACTIVE is True, "zeroai 实现未激活"
    print(f"  OK: _ZEROAI_IMPL_ACTIVE = {tui_agent._ZEROAI_IMPL_ACTIVE}")
    print(f"  OK: TOOLS count = {len(tui_agent.TOOLS)}")
    print(f"  OK: TOOL_MAP count = {len(tui_agent.TOOL_MAP)}")
    return tui_agent


def test_tools_from_zeroai(tui_agent):
    """测试 2：所有工具函数都来自 zeroai.tools.*"""
    print("\n[Test 2] 工具函数来源验证...")
    expected_modules = {
        "read_file": "zeroai.tools.file_manager",
        "write_file": "zeroai.tools.file_manager",
        "list_dir": "zeroai.tools.file_manager",
        "search_files": "zeroai.tools.file_manager",
        "delete_file": "zeroai.tools.file_manager",
        "move_file": "zeroai.tools.file_manager",
        "copy_file": "zeroai.tools.file_manager",
        "create_dir": "zeroai.tools.file_manager",
        "edit_file": "zeroai.tools.file_manager",
        "file_diff": "zeroai.tools.file_manager",
        "read_image": "zeroai.tools.file_manager",
        "run_command": "zeroai.tools.command_exec",
        "exec_python": "zeroai.tools.command_exec",
        "pip_install": "zeroai.tools.command_exec",
        "open_app": "zeroai.tools.network",
        "web_search": "zeroai.tools.network",
        "web_fetch": "zeroai.tools.network",
        "git_status": "zeroai.tools.network",
        "system_info": "zeroai.tools.system_check",
        "process_list": "zeroai.tools.system_check",
        "check_port": "zeroai.tools.system_check",
        "local_port_check": "zeroai.tools.system_check",
        "local_process_check": "zeroai.tools.system_check",
        "local_disk_check": "zeroai.tools.system_check",
        "local_service_check": "zeroai.tools.system_check",
        "local_firewall_check": "zeroai.tools.system_check",
        "local_user_check": "zeroai.tools.system_check",
        "local_monitor": "zeroai.tools.system_check",
        "security_audit": "zeroai.tools.security",
        "generate_word": "zeroai.tools.doc_gen",
        "generate_excel": "zeroai.tools.doc_gen",
        "generate_pdf": "zeroai.tools.doc_gen",
        "academic_search": "zeroai.tools.academic",
        "arxiv_search": "zeroai.tools.academic",
        "citation_check": "zeroai.tools.academic",
        "literature_review": "zeroai.tools.academic",
        "render_formula": "zeroai.tools.academic",
        "active_window": "zeroai.tools.window_mgr",
        "list_windows": "zeroai.tools.window_mgr",
        "read_screen_content": "zeroai.tools.window_mgr",
        "ssh_connect": "zeroai.tools.ssh_ops",
        "ssh_exec": "zeroai.tools.ssh_ops",
        "ssh_upload": "zeroai.tools.ssh_ops",
        "ssh_download": "zeroai.tools.ssh_ops",
        "ssh_deploy": "zeroai.tools.ssh_ops",
        "ssh_setup_samba_share": "zeroai.tools.ssh_ops",
        "ssh_list": "zeroai.tools.ssh_ops",
        "ssh_disconnect": "zeroai.tools.ssh_ops",
        "ssh_service_manage": "zeroai.tools.ssh_ops",
        "ssh_log_view": "zeroai.tools.ssh_ops",
        "ssh_process_check": "zeroai.tools.ssh_ops",
        "ssh_disk_analyze": "zeroai.tools.ssh_ops",
        "ssh_network_diag": "zeroai.tools.ssh_ops",
        "ssh_docker_manage": "zeroai.tools.ssh_ops",
        "ssh_firewall_manage": "zeroai.tools.ssh_ops",
        "ssh_health_check": "zeroai.tools.ssh_ops",
    }
    failed = []
    for name, expected_mod in expected_modules.items():
        fn = getattr(tui_agent, name, None)
        if fn is None:
            failed.append(f"  FAIL: tui_agent.{name} 不存在")
            continue
        actual_mod = getattr(fn, "__module__", "?")
        if actual_mod != expected_mod:
            failed.append(f"  FAIL: tui_agent.{name} 来自 {actual_mod}，期望 {expected_mod}")
    if failed:
        for f in failed:
            print(f)
        raise AssertionError(f"{len(failed)} 个工具函数来源错误")
    print(f"  OK: 全部 {len(expected_modules)} 个工具函数都来自 zeroai.tools.*")


def test_core_from_zeroai(tui_agent):
    """测试 3：core 层函数都来自 zeroai.core.*"""
    print("\n[Test 3] core 层函数来源验证...")
    expected_modules = {
        "_get_desktop_dir": "zeroai.core.paths",
        "_resolve_save_path": "zeroai.core.paths",
        "_find_resource_dir": "zeroai.core.paths",
        "_ensure_user_dir": "zeroai.core.paths",
        "_get_resource_dir": "zeroai.core.paths",
        "RuntimeCache": "zeroai.core.runtime",
        "runtime_cache": "zeroai.core.runtime",
        "_is_stopped": "zeroai.core.runtime",
        "_interruptible_await": "zeroai.core.runtime",
        "_interruptible_sleep": "zeroai.core.runtime",
        "_obfuscate": "zeroai.core.secrets",
        "_deobfuscate": "zeroai.core.secrets",
        "_load_config": "zeroai.core.secrets",
        "_save_config": "zeroai.core.secrets",
        "_get_api_key": "zeroai.core.secrets",
        "_make_openai_client": "zeroai.core.secrets",
        "MODEL_CONFIGS": "zeroai.core.constants",
        "EXPERT_TEAM": "zeroai.core.constants",
        "WORK_MODE": "zeroai.core.constants",
        "PERMISSION_LEVEL": "zeroai.core.constants",
        "MAX_FILE_SIZE": "zeroai.core.constants",
        "route_expert": "zeroai.core.expert_route",
        "route_expert_glm": "zeroai.core.expert_route",
        "get_expert_config": "zeroai.core.expert_route",
        "LRUCache": "zeroai.core.expert_route",
        "cleanup_context": "zeroai.core.context_compress",
        "compress_context": "zeroai.core.context_compress",
        "cleanup_and_compress": "zeroai.core.context_compress",
        "get_active_model_info": "zeroai.core.model_manager",
        "detect_ollama_models": "zeroai.core.model_manager",
        "get_client": "zeroai.core.model_manager",
        "get_model_name": "zeroai.core.model_manager",
        "get_model_label": "zeroai.core.model_manager",
        "_strip_model_tokens": "zeroai.core.response_utils",
        "_parse_think_tags": "zeroai.core.response_utils",
        "_jaccard_similarity": "zeroai.core.response_utils",
        "_truncate_expert_response": "zeroai.core.response_utils",
        "_sanitize_identity_leak": "zeroai.core.response_utils",
    }
    failed = []
    for name, expected_mod in expected_modules.items():
        obj = getattr(tui_agent, name, None)
        if obj is None:
            failed.append(f"  FAIL: tui_agent.{name} 不存在")
            continue
        # 常量（如 MODEL_CONFIGS）可能没有 __module__，跳过模块检查
        if callable(obj) or isinstance(obj, type):
            actual_mod = getattr(obj, "__module__", "?")
            if actual_mod != expected_mod:
                failed.append(f"  FAIL: tui_agent.{name} 来自 {actual_mod}，期望 {expected_mod}")
    if failed:
        for f in failed:
            print(f)
        raise AssertionError(f"{len(failed)} 个 core 函数来源错误")
    print(f"  OK: 全部 {len(expected_modules)} 个 core 层符号验证通过（callable 检查模块来源）")


def test_tools_toolmap_consistency(tui_agent):
    """测试 4：TOOLS 和 TOOL_MAP 与 registry 中的一致"""
    print("\n[Test 4] TOOLS / TOOL_MAP 一致性验证...")
    from zeroai.tools.registry import TOOLS as REG_TOOLS, TOOL_MAP as REG_TOOL_MAP

    assert tui_agent.TOOLS is REG_TOOLS, "tui_agent.TOOLS 不是 registry.TOOLS"
    assert tui_agent.TOOL_MAP is REG_TOOL_MAP, "tui_agent.TOOL_MAP 不是 registry.TOOL_MAP"
    print("  OK: tui_agent.TOOLS is registry.TOOLS")
    print("  OK: tui_agent.TOOL_MAP is registry.TOOL_MAP")

    # 验证 TOOLS 中所有 name 都在 TOOL_MAP 中
    tools_names = {t["function"]["name"] for t in tui_agent.TOOLS}
    map_keys = set(tui_agent.TOOL_MAP.keys())
    assert tools_names == map_keys, f"TOOLS 和 TOOL_MAP 的 key 不一致：差异={tools_names ^ map_keys}"
    print(f"  OK: TOOLS({len(tools_names)}) 和 TOOL_MAP({len(map_keys)}) 的 key 完全一致")


def test_tool_callables(tui_agent):
    """测试 5：TOOL_MAP 中所有 value 都是可调用对象"""
    print("\n[Test 5] TOOL_MAP 可调用性验证...")
    non_callable = []
    for name, fn in tui_agent.TOOL_MAP.items():
        if not callable(fn):
            non_callable.append(name)
    if non_callable:
        raise AssertionError(f"以下工具不可调用: {non_callable}")
    print(f"  OK: 全部 {len(tui_agent.TOOL_MAP)} 个工具都是可调用对象")


def test_real_tool_calls(tui_agent):
    """测试 6：关键工具函数实际调用（只测试无副作用的）"""
    print("\n[Test 6] 关键工具函数实际调用验证...")

    # 6.1 read_file 读取自身
    result = tui_agent.read_file(__file__, max_length=100)
    assert isinstance(result, str), "read_file 返回值不是 str"
    assert "阶段3" in result or "regression" in result.lower() or "test" in result.lower(), \
        f"read_file 内容异常: {result[:50]}"
    print(f"  OK: read_file 读取自身文件成功（{len(result)} 字符）")

    # 6.2 list_dir 列出当前目录
    result = tui_agent.list_dir(".")
    assert isinstance(result, str), "list_dir 返回值不是 str"
    assert "tui_agent.py" in result or "zeroai" in result, f"list_dir 内容异常: {result[:50]}"
    print(f"  OK: list_dir 列出当前目录成功（{len(result)} 字符）")

    # 6.3 system_info
    result = tui_agent.system_info()
    assert isinstance(result, str), "system_info 返回值不是 str"
    print(f"  OK: system_info 返回系统信息（{len(result)} 字符）")

    # 6.4 search_files 搜索自身
    result = tui_agent.search_files("def test_", path=".")
    assert isinstance(result, str), "search_files 返回值不是 str"
    print(f"  OK: search_files 搜索成功（{len(result)} 字符）")

    # 6.5 _get_desktop_dir
    desktop = tui_agent._get_desktop_dir()
    assert isinstance(desktop, str), "_get_desktop_dir 返回值不是 str"
    assert desktop, "_get_desktop_dir 返回空字符串"
    print(f"  OK: _get_desktop_dir = {desktop}")

    # 6.6 route_expert 路由测试
    expert = tui_agent.route_expert("帮我写一个 Python 函数")
    assert isinstance(expert, str), "route_expert 返回值不是 str"
    print(f"  OK: route_expert('帮我写一个 Python 函数') = {expert}")

    # 6.7 get_model_label
    label = tui_agent.get_model_label()
    assert isinstance(label, str), "get_model_label 返回值不是 str"
    print(f"  OK: get_model_label() = {label}")

    # 6.8 render_formula 公式渲染
    result = tui_agent.render_formula("E=mc^2")
    assert isinstance(result, str), "render_formula 返回值不是 str"
    print(f"  OK: render_formula('E=mc^2') = {result[:50]}")

    # 6.9 _parse_think_tags（返回顺序：think_content, body_content）
    think_content, body_content = tui_agent._parse_think_tags("<think>思路</think>回答")
    assert think_content == "思路", f"_parse_think_tags think_content 异常: {think_content}"
    assert body_content == "回答", f"_parse_think_tags body_content 异常: {body_content}"
    print(f"  OK: _parse_think_tags 解析正确（think={think_content}, body={body_content}）")


def test_tool_signatures(tui_agent):
    """测试 7：工具函数签名一致性（与 tui_agent.py 本地定义对齐）"""
    print("\n[Test 7] 工具函数签名验证...")
    expected_sigs = {
        "read_file": ["path", "max_length"],
        "write_file": ["path", "content"],
        "list_dir": ["path", "recursive", "max_depth"],
        "search_files": ["pattern", "path"],
        "delete_file": ["path"],
        "move_file": ["src", "dst"],
        "copy_file": ["src", "dst"],
        "create_dir": ["path"],
        "edit_file": ["path", "operation", "line", "content", "start_line", "end_line"],
        "file_diff": ["path_a", "path_b"],
        "read_image": ["path"],
        "run_command": ["command", "skip_translate"],
        "exec_python": ["code", "timeout"],
        "pip_install": ["package", "action"],
        "web_search": ["query", "num_results"],
        "web_fetch": ["url", "max_length"],
        "git_status": ["repo_path"],
        "system_info": [],
        "process_list": ["name_filter"],
        "check_port": ["port"],
        "render_formula": ["latex", "style"],
        "active_window": [],
        "list_windows": [],
        "read_screen_content": ["max_length"],
    }
    failed = []
    for name, expected_params in expected_sigs.items():
        fn = getattr(tui_agent, name, None)
        if fn is None:
            failed.append(f"  FAIL: tui_agent.{name} 不存在")
            continue
        sig = inspect.signature(fn)
        actual_params = list(sig.parameters.keys())
        if actual_params != expected_params:
            failed.append(f"  FAIL: tui_agent.{name} 签名 {actual_params}，期望 {expected_params}")
    if failed:
        for f in failed:
            print(f)
        raise AssertionError(f"{len(failed)} 个工具签名错误")
    print(f"  OK: 全部 {len(expected_sigs)} 个工具签名验证通过")


def test_no_circular_import():
    """测试 8：验证无循环导入问题"""
    print("\n[Test 8] 循环导入验证...")
    # 强制重新导入，检查是否有循环导入警告
    import importlib
    import tui_agent as ta
    importlib.reload(ta)
    assert ta._ZEROAI_IMPL_ACTIVE is True, "重载后 zeroai 实现未激活"
    print("  OK: tui_agent 重载后 zeroai 实现仍激活")
    print(f"  OK: TOOLS count = {len(ta.TOOLS)}, TOOL_MAP count = {len(ta.TOOL_MAP)}")


def main():
    print("=" * 70)
    print("阶段3 回归测试：tui_agent.py 内部调用切换到 zeroai 包")
    print("=" * 70)

    tui_agent = test_import()
    test_tools_from_zeroai(tui_agent)
    test_core_from_zeroai(tui_agent)
    test_tools_toolmap_consistency(tui_agent)
    test_tool_callables(tui_agent)
    test_real_tool_calls(tui_agent)
    test_tool_signatures(tui_agent)
    test_no_circular_import()

    print("\n" + "=" * 70)
    print("✅ 全部 8 项测试通过！阶段3 切换成功")
    print("=" * 70)
    print("\n切换摘要：")
    print(f"  - 工具函数：56 个，全部来自 zeroai.tools.*")
    print(f"  - core 层函数：38+ 个符号，全部来自 zeroai.core.*")
    print(f"  - TOOLS / TOOL_MAP：与 zeroai.tools.registry 共享同一对象")
    print(f"  - 原有函数定义：保留作为备份（_ZEROAI_IMPL_ACTIVE=True 时不被调用）")
    print(f"  - 回退机制：注释切换块即可恢复本地实现")


if __name__ == "__main__":
    main()
