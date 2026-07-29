"""NOPQ 阶段综合测试

测试覆盖：
- N：代码执行沙箱（CodeSandbox / CodeSafetyChecker）
- O：多 Agent 协作增强（MessageBus / Blackboard / EnhancedMultiAgentCollaborator）
- P：流式思维链 + 中断响应 + 进度跟踪（StreamingThoughtEmitter / InterruptionHandler / ProgressTracker）
  + AgentLoop 集成 ProgressTracker
- Q：项目代码知识图谱（CodeKnowledgeGraph AST 解析 + 自然语言查询）

运行：
    python test_nopq_stages.py
"""
import os
import sys
import time
import asyncio
import tempfile

# 确保项目根目录在 path 中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def test_n_sandbox():
    """测试 N 阶段：代码执行沙箱"""
    print("\n=== 测试 N 阶段：代码执行沙箱 ===")
    from zeroai.core.sandbox import CodeSandbox, CodeSafetyChecker, check_code_safety

    # 测试安全检查
    print("[N.1] 测试代码安全检查...")
    safe_code = "print('hello')"
    is_safe, issues = check_code_safety(safe_code)
    assert is_safe, f"安全代码被误判: {issues}"
    print(f"  ✓ 安全代码通过检查: {safe_code!r}")

    dangerous_code = "import os\nos.system('rm -rf /')"
    is_safe, issues = check_code_safety(dangerous_code)
    assert not is_safe, "危险代码未被检测到"
    print(f"  ✓ 危险代码被拦截: {issues}")

    # 测试沙箱执行
    print("[N.2] 测试沙箱执行...")
    sandbox = CodeSandbox(timeout=5, max_memory_mb=128)
    result = sandbox.execute("print(1 + 1)")
    assert result.get("success"), f"执行失败: {result}"
    assert "2" in result.get("stdout", ""), f"输出错误: {result}"
    print(f"  ✓ 简单代码执行成功: stdout={result['stdout'].strip()!r}")

    # 测试超时
    print("[N.3] 测试超时保护...")
    sandbox_short = CodeSandbox(timeout=1)
    result = sandbox_short.execute("import time\ntime.sleep(3)")
    # 超时返回错误
    assert not result.get("success", True), "超时未生效"
    print(f"  ✓ 超时保护生效: returncode={result.get('returncode')}")

    print("✓ N 阶段全部通过")


def test_o_agent_bus():
    """测试 O 阶段：多 Agent 消息总线"""
    print("\n=== 测试 O 阶段：多 Agent 消息总线 ===")
    from zeroai.core.agent_bus import MessageBus, Blackboard, AgentMessage, get_message_bus

    # 测试消息总线
    print("[O.1] 测试消息总线...")
    bus = MessageBus()
    received = []

    def handler(msg):
        received.append(msg)

    bus.subscribe("test_topic", handler)
    msg = AgentMessage(
        sender="agent_a",
        topic="test_topic",
        content={"data": 123},
        msg_type="notification",
    )
    count = bus.publish(msg)
    assert count == 1, f"订阅者数量错误: {count}"
    assert len(received) == 1, "消息未送达"
    print(f"  ✓ 消息发布订阅成功: {received[0].content}")

    # 测试黑板
    print("[O.2] 测试共享黑板...")
    board = Blackboard()
    version = board.write("ns1", "key1", "value1", writer="agent_a")
    assert version == 1, f"首次写入版本应为1: {version}"
    val = board.read("ns1", "key1")
    assert val == "value1", f"读取值错误: {val}"
    print(f"  ✓ 黑板读写成功: version={version}, value={val}")

    # 测试版本递增
    version2 = board.write("ns1", "key1", "value2", writer="agent_b")
    assert version2 == 2, f"版本递增错误: {version2}"
    print(f"  ✓ 版本递增正确: {version} -> {version2}")

    print("✓ O 阶段全部通过")


def test_p_streaming():
    """测试 P 阶段：流式思维链 + 中断响应 + 进度跟踪"""
    print("\n=== 测试 P 阶段：流式思维链 ===")
    from zeroai.core.streaming import (
        StreamingThoughtEmitter,
        InterruptionHandler,
        ProgressTracker,
        ThoughtChunk,
    )

    # 测试流式发射器
    print("[P.1.1] 测试流式思维链发射器...")
    chunks = []
    emitter = StreamingThoughtEmitter(
        on_chunk=lambda c: chunks.append(c.text),
        buffer_mode="immediate",
    )
    emitter.start_thought("测试")
    emitter.append_chunk("Hello ")
    emitter.append_chunk("World")
    full = emitter.end_thought()
    assert "Hello" in full and "World" in full, f"完整文本错误: {full}"
    assert len(chunks) >= 2, f"chunk 数量错误: {len(chunks)}"
    print(f"  ✓ 流式输出: chunks={len(chunks)}, full={full!r}")

    # 测试中断处理器
    print("[P.1.2] 测试中断响应...")
    handler = InterruptionHandler()
    assert not handler.check(), "初始状态应为未中断"
    handler.interrupt("测试中断")
    assert handler.check(), "中断后应检测到"
    assert "测试中断" in handler.reason, f"中断原因错误: {handler.reason}"
    handler.reset()
    assert not handler.check(), "重置后应为未中断"
    print(f"  ✓ 中断响应: reason={handler.reason!r}")

    # 测试进度跟踪器
    print("[P.1.3] 测试进度跟踪...")
    tracker = ProgressTracker()
    call_id = tracker.start("test_tool", {"arg": "value"})
    tracker.update(call_id, progress=0.5, message="进行中")
    progress = tracker.get_progress(call_id)
    assert progress.progress == 0.5, f"进度错误: {progress.progress}"
    tracker.complete(call_id, result="done")
    progress = tracker.get_progress(call_id)
    assert progress.status == "done", f"状态错误: {progress.status}"
    print(f"  ✓ 进度跟踪: {progress.tool_name} -> {progress.status}")

    # 测试进度条渲染
    bar = tracker.render_progress_bar(call_id)
    assert "test_tool" in bar, f"进度条错误: {bar}"
    print(f"  ✓ 进度条: {bar}")

    print("✓ P.1 阶段全部通过")


def test_p2_agent_loop_integration():
    """测试 P.2 阶段：AgentLoop 集成 ProgressTracker"""
    print("\n=== 测试 P.2 阶段：AgentLoop 进度跟踪集成 ===")
    from zeroai.core.agent import AgentLoop
    from zeroai.core.streaming import reset_streaming

    reset_streaming()

    # 创建启用进度跟踪的 AgentLoop
    loop = AgentLoop(
        enable_progress_tracker=True,
        enable_streaming_thought=True,
        max_steps=2,
    )
    assert loop._progress_tracker is not None, "进度跟踪器未初始化"
    assert loop._streaming_emitter is not None, "流式发射器未初始化"
    assert loop._interrupt_handler is not None, "中断处理器未初始化"
    print("  ✓ AgentLoop 进度跟踪组件已初始化")

    # 测试中断方法
    loop.interrupt("测试中断")
    assert loop._check_stopped(), "中断未生效"
    print("  ✓ AgentLoop 中断响应正常")

    # 测试进度摘要方法
    summary = loop.get_progress_summary()
    stats = loop.get_progress_stats()
    # 初始状态可能为空字符串（无调用）或包含"无工具调用"
    assert isinstance(summary, str), f"summary 类型错误: {type(summary)}"
    assert isinstance(stats, dict), f"stats 类型错误: {type(stats)}"
    print(f"  ✓ AgentLoop 进度查询方法正常: stats={stats}")

    reset_streaming()
    print("✓ P.2 阶段全部通过")


def test_q_code_knowledge_graph():
    """测试 Q 阶段：项目代码知识图谱"""
    print("\n=== 测试 Q 阶段：代码知识图谱 ===")
    from zeroai.core.code_knowledge_graph import (
        CodeKnowledgeGraph,
        CodeNode,
        CodeEdge,
        get_code_knowledge_graph,
        reset_code_knowledge_graph,
    )

    reset_code_knowledge_graph()
    graph = CodeKnowledgeGraph()

    # 创建临时测试文件
    print("[Q.1] 测试 AST 解析...")
    test_code = '''"""测试模块"""
import os
from typing import List

class BaseClass:
    """基类"""
    def base_method(self):
        return "base"

def hello(name):
    """打招呼"""
    print(f"hello {name}")
    return name

def caller():
    """调用者"""
    hello("world")
    return True
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(test_code)
        test_file = f.name

    try:
        count = graph.index_file(test_file, root_dir=os.path.dirname(test_file))
        assert count > 0, f"索引节点数为 0: {count}"
        print(f"  ✓ 索引成功: {count} 个节点")

        # 验证节点类型
        stats = graph.get_stats()
        assert stats["total_nodes"] > 0, "节点数为 0"
        print(f"  ✓ 统计: {stats['node_types']}")

        # 查找函数
        nodes = graph.find_nodes("hello")
        assert len(nodes) >= 1, "未找到 hello 函数"
        print(f"  ✓ 查找函数: hello -> {nodes[0].qualified_name}")

        # 查找类
        nodes = graph.find_nodes("BaseClass")
        assert len(nodes) >= 1, "未找到 BaseClass 类"
        print(f"  ✓ 查找类: BaseClass -> {nodes[0].qualified_name}")

        # 解析外部引用后，查找调用者
        graph._resolve_external_references()
        callers = graph.find_callers("hello")
        assert len(callers) >= 1, "未找到 hello 的调用者"
        print(f"  ✓ 查找调用者: hello <- {[c.qualified_name for c in callers]}")

        # 查找被调用者
        callees = graph.find_callees("caller")
        callee_names = [c.name for c in callees]
        assert "hello" in callee_names, f"caller 的被调用者中应有 hello: {callee_names}"
        print(f"  ✓ 查找被调用者: caller -> {callee_names}")

    finally:
        os.unlink(test_file)

    print("✓ Q.1 阶段全部通过")


def test_q2_natural_language_query():
    """测试 Q.2 阶段：自然语言查询"""
    print("\n=== 测试 Q.2 阶段：自然语言查询 ===")
    from zeroai.core.code_knowledge_graph import CodeKnowledgeGraph

    graph = CodeKnowledgeGraph()

    # 创建测试代码
    test_code = '''"""测试模块"""
class Animal:
    def speak(self):
        pass

class Dog(Animal):
    def speak(self):
        return "woof"

class Cat(Animal):
    def speak(self):
        return "meow"

def make_sound(animal):
    return animal.speak()

def main():
    dog = Dog()
    make_sound(dog)
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(test_code)
        test_file = f.name

    try:
        graph.index_file(test_file, root_dir=os.path.dirname(test_file))
        graph._resolve_external_references()

        # 测试标识符提取
        print("[Q.2.1] 测试标识符提取...")
        ident = graph._extract_identifier("谁调用了 make_sound 函数？")
        assert ident == "make_sound", f"标识符提取错误: {ident}"
        print(f"  ✓ 提取: '谁调用了 make_sound 函数？' -> {ident!r}")

        ident = graph._extract_identifier("Animal 的子类有哪些？")
        assert ident == "Animal", f"标识符提取错误: {ident}"
        print(f"  ✓ 提取: 'Animal 的子类有哪些？' -> {ident!r}")

        # 测试调用者查询
        print("[Q.2.2] 测试调用者查询...")
        answer = graph.query("谁调用了 make_sound？")
        assert "main" in answer, f"调用者查询错误: {answer}"
        print(f"  ✓ 查询: '谁调用了 make_sound？' -> 找到 main")

        # 测试子类查询
        print("[Q.2.3] 测试子类查询...")
        answer = graph.query("Animal 的子类有哪些？")
        assert "Dog" in answer and "Cat" in answer, f"子类查询错误: {answer}"
        print(f"  ✓ 查询: 'Animal 的子类' -> 找到 Dog, Cat")

        # 测试定义位置查询
        print("[Q.2.4] 测试定义位置查询...")
        answer = graph.query("Dog 定义在哪里？")
        assert "Dog" in answer, f"定义查询错误: {answer}"
        print(f"  ✓ 查询: 'Dog 定义在哪里？' -> 找到定义")

        # 测试调用链查询
        print("[Q.2.5] 测试调用链查询...")
        answer = graph.query("make_sound 的调用链")
        assert "make_sound" in answer, f"调用链查询错误: {answer}"
        print(f"  ✓ 查询: 'make_sound 的调用链' -> 找到调用链")

    finally:
        os.unlink(test_file)

    print("✓ Q.2 阶段全部通过")


def test_q_tools_integration():
    """测试 Q 阶段工具函数集成"""
    print("\n=== 测试 Q 阶段工具函数集成 ===")
    from zeroai.tools.command_exec import code_graph_index, code_graph_query, code_graph_stats
    from zeroai.tools.registry import TOOL_MAP

    # 验证工具已注册
    assert "code_graph_index" in TOOL_MAP, "code_graph_index 未注册"
    assert "code_graph_query" in TOOL_MAP, "code_graph_query 未注册"
    assert "code_graph_stats" in TOOL_MAP, "code_graph_stats 未注册"
    print("  ✓ 工具已注册到 TOOL_MAP")

    # 索引项目自身
    print("[Q.工具] 索引项目自身...")
    result = code_graph_index(PROJECT_ROOT)
    assert "代码知识图谱构建完成" in result, f"索引失败: {result[:200]}"
    print(f"  ✓ 索引成功: {result.split(chr(10))[0]}")

    # 查询统计
    stats = code_graph_stats()
    assert "节点总数" in stats, f"统计查询失败: {stats[:200]}"
    print(f"  ✓ 统计查询正常")

    # 自然语言查询
    answer = code_graph_query("AgentLoop 定义在哪里？")
    assert "AgentLoop" in answer, f"查询失败: {answer[:200]}"
    print(f"  ✓ 自然语言查询正常: 找到 AgentLoop")

    print("✓ Q 阶段工具函数集成测试通过")


def test_imports():
    """测试模块导入完整性"""
    print("\n=== 测试模块导入完整性 ===")
    import zeroai
    print(f"  ✓ zeroai 版本: {zeroai.__version__}")

    from zeroai.core import (
        CodeSafetyChecker, CodeSandbox, check_code_safety,
        AgentMessage, MessageBus, Blackboard, get_message_bus, get_blackboard,
        RoleNode, CollaborationContext, RoleDependencyGraph, EnhancedMultiAgentCollaborator,
        ThoughtChunk, StreamingThoughtEmitter, InterruptionHandler,
        ToolCallProgress, ProgressTracker,
        get_streaming_emitter, get_interrupt_handler, get_progress_tracker, reset_streaming,
        CodeNode, CodeEdge, CodeKnowledgeGraph,
        get_code_knowledge_graph, reset_code_knowledge_graph,
    )
    print("  ✓ 所有新模块导入成功")

    # 验证 AgentLoop 新参数
    from zeroai.core.agent import AgentLoop
    loop = AgentLoop(enable_progress_tracker=True, enable_streaming_thought=True)
    assert hasattr(loop, "_progress_tracker"), "AgentLoop 缺少 _progress_tracker"
    assert hasattr(loop, "_streaming_emitter"), "AgentLoop 缺少 _streaming_emitter"
    assert hasattr(loop, "_interrupt_handler"), "AgentLoop 缺少 _interrupt_handler"
    assert hasattr(loop, "get_progress_summary"), "AgentLoop 缺少 get_progress_summary"
    assert hasattr(loop, "interrupt"), "AgentLoop 缺少 interrupt 方法"
    print("  ✓ AgentLoop P.2 集成验证通过")
    reset_streaming()


def main():
    """主测试函数"""
    print("=" * 60)
    print("NOPQ 阶段综合测试")
    print("=" * 60)

    tests = [
        ("模块导入", test_imports),
        ("N 沙箱", test_n_sandbox),
        ("O 消息总线", test_o_agent_bus),
        ("P.1 流式思维链", test_p_streaming),
        ("P.2 AgentLoop 集成", test_p2_agent_loop_integration),
        ("Q.1 代码知识图谱", test_q_code_knowledge_graph),
        ("Q.2 自然语言查询", test_q2_natural_language_query),
        ("Q 工具集成", test_q_tools_integration),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"✗ {name} 测试失败: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 项")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
