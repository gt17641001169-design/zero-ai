"""ZeroAI 工具函数可调用性验证脚本

逐个验证 registry.py 中 TOOLS 和 TOOL_MAP 的所有工具函数：
1. 验证导入是否成功
2. 验证 TOOLS schema 与 TOOL_MAP key 的一致性
3. 验证每个工具函数是否可调用
4. 验证函数签名与 schema parameters 是否匹配

不实际执行工具（避免副作用），只验证可调用性。
"""
import sys
import inspect
from pathlib import Path

# 确保项目根目录在 sys.path
project_root = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_root))


def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_imports():
    """测试所有工具模块的导入"""
    print_section("1. 测试工具模块导入")
    modules = [
        "zeroai.tools",
        "zeroai.tools.registry",
        "zeroai.tools.file_manager",
        "zeroai.tools.command_exec",
        "zeroai.tools.network",
        "zeroai.tools.system_check",
        "zeroai.tools.security",
        "zeroai.tools.doc_gen",
        "zeroai.tools.academic",
        "zeroai.tools.window_mgr",
        "zeroai.tools.ssh_ops",
        "zeroai.tools.voice",
        "zeroai.tools.clipboard",
        "zeroai.tools.render",
        "zeroai.tools.base",
        "zeroai.tools.file_ops",
    ]
    passed, failed = 0, 0
    for mod_name in modules:
        try:
            __import__(mod_name)
            print(f"  [OK]  {mod_name}")
            passed += 1
        except Exception as e:
            print(f"  [ERR] {mod_name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n  导入测试: {passed} 通过, {failed} 失败")
    return failed == 0


def test_schema_map_consistency():
    """测试 TOOLS schema 与 TOOL_MAP 的一致性"""
    print_section("2. 测试 TOOLS schema 与 TOOL_MAP 一致性")
    from zeroai.tools.registry import TOOLS, TOOL_MAP

    schema_names = set()
    duplicate_names = []
    for entry in TOOLS:
        name = entry.get("function", {}).get("name")
        if not name:
            print("  [ERR] 发现没有 name 字段的 schema 条目")
            continue
        if name in schema_names:
            duplicate_names.append(name)
        schema_names.add(name)

    map_names = set(TOOL_MAP.keys())

    only_in_schema = schema_names - map_names
    only_in_map = map_names - schema_names

    print(f"  TOOLS schema 中工具数: {len(schema_names)}")
    print(f"  TOOL_MAP 中工具数: {len(map_names)}")

    if duplicate_names:
        print(f"  [ERR] TOOLS 中重复的工具名: {duplicate_names}")
    if only_in_schema:
        print(f"  [ERR] 只在 TOOLS schema 中存在（TOOL_MAP 缺失）: {only_in_schema}")
    if only_in_map:
        print(f"  [ERR] 只在 TOOL_MAP 中存在（TOOLS schema 缺失）: {only_in_map}")

    if not duplicate_names and not only_in_schema and not only_in_map:
        print(f"  [OK]  TOOLS 与 TOOL_MAP 完全一致（{len(schema_names)} 个工具）")
        return True
    return False


def test_tool_callability():
    """测试每个工具函数的可调用性"""
    print_section("3. 测试每个工具函数的可调用性")
    from zeroai.tools.registry import TOOL_MAP

    passed, failed = 0, 0
    for name, func in sorted(TOOL_MAP.items()):
        # 1. 检查是否可调用
        if not callable(func):
            print(f"  [ERR] {name}: 不可调用 (type={type(func).__name__})")
            failed += 1
            continue
        # 2. 检查是否为函数/方法
        if not (inspect.isfunction(func) or inspect.ismethod(func) or inspect.isbuiltin(func)):
            print(f"  [WARN] {name}: 类型异常 ({type(func).__name__})")
        # 3. 检查签名
        try:
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            print(f"  [OK]  {name}({', '.join(params)})")
            passed += 1
        except (ValueError, TypeError) as e:
            print(f"  [ERR] {name}: 无法获取签名 - {e}")
            failed += 1
    print(f"\n  可调用性测试: {passed} 通过, {failed} 失败")
    return failed == 0


def test_schema_param_match():
    """测试 schema parameters 与函数签名是否匹配"""
    print_section("4. 测试 schema parameters 与函数签名匹配")
    from zeroai.tools.registry import TOOLS, TOOL_MAP

    passed, failed = 0, 0
    for entry in TOOLS:
        func_def = entry.get("function", {})
        name = func_def.get("name")
        if not name or name not in TOOL_MAP:
            failed += 1
            continue
        func = TOOL_MAP[name]
        try:
            sig = inspect.signature(func)
            func_params = set(sig.parameters.keys())
            schema_props = func_def.get("parameters", {}).get("properties", {})
            schema_params = set(schema_props.keys())
            schema_required = set(func_def.get("parameters", {}).get("required", []))

            # 检查 schema required 是否都在 schema_params 中
            missing_in_props = schema_required - schema_params
            if missing_in_props:
                print(f"  [ERR] {name}: required 字段 {missing_in_props} 不在 properties 中")

            # 检查函数参数是否覆盖 schema required
            missing_in_func = schema_required - func_params
            if missing_in_func:
                print(f"  [ERR] {name}: 函数缺少 required 参数 {missing_in_func}")

            # 检查 schema 多余的字段（schema 有的，函数没有的）
            extra_in_schema = schema_params - func_params
            if extra_in_schema:
                print(f"  [WARN] {name}: schema 声明了但函数没有的参数 {extra_in_schema}")

            # 检查函数多余的字段（函数有的，schema 没有的）
            extra_in_func = func_params - schema_params
            if extra_in_func:
                # 内部参数（如 _internal）是允许的
                public_extra = {p for p in extra_in_func if not p.startswith("_")}
                if public_extra:
                    print(f"  [INFO] {name}: 函数有但 schema 没声明的参数 {public_extra}")

            if not missing_in_props and not missing_in_func:
                print(f"  [OK]  {name}: 签名匹配")
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  [ERR] {name}: 签名分析异常 - {e}")
            failed += 1
    print(f"\n  签名匹配测试: {passed} 通过, {failed} 失败")
    return failed == 0


def test_voice_tools_unregistered():
    """检查 voice.py 是否有未注册的工具函数"""
    print_section("5. 检查 voice.py 未注册的工具函数")
    try:
        from zeroai.tools.voice import speak_tts, listen_asr
        from zeroai.tools.registry import TOOL_MAP
        unregistered = []
        for name, func in [("speak_tts", speak_tts), ("listen_asr", listen_asr)]:
            if name not in TOOL_MAP:
                unregistered.append(name)
                print(f"  [WARN] {name}: 存在于 voice.py 但未注册到 TOOL_MAP")
            else:
                print(f"  [OK]  {name}: 已注册")
        if unregistered:
            print(f"\n  未注册工具: {unregistered}")
            return False
        return True
    except ImportError as e:
        print(f"  [ERR] 导入 voice.py 失败: {e}")
        return False


def test_check_port_dead_code():
    """检查 system_check.py 的 check_port 死代码（使用 AST 精确检测）"""
    print_section("6. 检查 system_check.py check_port 死代码")
    try:
        import ast
        import zeroai.tools.system_check as sc
        src = inspect.getsource(sc.check_port)

        # 使用 AST 检测真正的死代码（return 之后的同级语句）
        tree = ast.parse(src)

        dead_code_count = 0

        def check_dead_code_in_body(body, context=""):
            """递归检查函数体中的死代码"""
            nonlocal dead_code_count
            found_terminator = False
            for node in body:
                if found_terminator:
                    # 找到终止语句后的同级语句 = 死代码
                    dead_code_count += 1
                    if hasattr(node, "lineno"):
                        print(f"  [WARN] 死代码 行 {node.lineno}: {type(node).__name__} ({context})")
                    return
                # return / raise / break / continue 是终止语句
                if isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                    found_terminator = True
                # 递归检查子语句块
                for field in ast.iter_fields(node):
                    if isinstance(field[1], list):
                        for item in field[1]:
                            if isinstance(item, ast.stmt):
                                # if/for/while/try 等复合语句的 body
                                if hasattr(item, "body"):
                                    check_dead_code_in_body(item.body, f"{type(node).__name__} body")
                                if hasattr(item, "orelse"):
                                    check_dead_code_in_body(item.orelse, f"{type(node).__name__} orelse")
                                if hasattr(item, "finalbody"):
                                    check_dead_code_in_body(item.finalbody, f"{type(node).__name__} finalbody")
                                if hasattr(item, "handlers"):
                                    for h in item.handlers:
                                        check_dead_code_in_body(h.body, f"{type(node).__name__} handler")

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                check_dead_code_in_body(node.body, node.name)

        if dead_code_count == 0:
            print(f"  [OK]  check_port 无死代码")
            return True
        else:
            print(f"  [WARN] check_port 发现 {dead_code_count} 处死代码")
            return False
    except Exception as e:
        print(f"  [ERR] 检查失败: {e}")
        return False


def main():
    print("ZeroAI 工具函数可调用性验证")
    print(f"项目根目录: {project_root}")
    print(f"Python: {sys.version.split()[0]}")

    results = []
    results.append(("模块导入", test_imports()))
    results.append(("Schema-Map一致性", test_schema_map_consistency()))
    results.append(("工具可调用性", test_tool_callability()))
    results.append(("签名匹配", test_schema_param_match()))
    results.append(("voice.py未注册工具", test_voice_tools_unregistered()))
    results.append(("check_port死代码", test_check_port_dead_code()))

    print_section("测试总结")
    all_pass = True
    for name, passed in results:
        status = "[OK]  " if passed else "[FAIL]"
        print(f"  {status} {name}")
        if not passed:
            all_pass = False

    print(f"\n{'='*60}")
    if all_pass:
        print("  所有测试通过！")
        sys.exit(0)
    else:
        print("  存在测试失败，请检查上述 [ERR]/[WARN] 项")
        sys.exit(1)


if __name__ == "__main__":
    main()
