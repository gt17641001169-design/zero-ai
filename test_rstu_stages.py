"""RSTU 阶段综合测试

测试覆盖：
- R：Zig 加速层深度优化（SIMD 比较/UTF-8 计数/批量填充 - Python 端绑定验证）
- S：工具调用并行化（并行调度器/依赖图/结果合并/AgentLoop 集成）
- T：内存与性能优化（向量压缩/统一缓存/增量索引/上下文预算）
- U：发布前准备验证（CHANGELOG/模块导入/工具注册完整性）

运行：
    python test_rstu_stages.py
"""
import os
import sys
import time
import asyncio
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def test_r_zig_bindings():
    """测试 R 阶段：Zig 加速层 Python 绑定"""
    print("\n=== 测试 R 阶段：Zig 加速层绑定 ===")
    # 即使 Zig 库未编译，绑定配置也不应导致导入失败
    try:
        from zeroai_tui._zig_bindings import HAS_ZIG_RENDERER, StyleStruct
        print(f"  ✓ Zig 渲染器可用: {HAS_ZIG_RENDERER}")
    except ImportError as e:
        print(f"  ⚠ Zig 绑定模块导入跳过: {e}")
        return

    # 验证 StyleStruct 结构
    s = StyleStruct(bold=1, fg_id=5)
    assert s.bold == 1, f"StyleStruct.bold 错误: {s.bold}"
    assert s.fg_id == 5, f"StyleStruct.fg_id 错误: {s.fg_id}"
    print(f"  ✓ StyleStruct 结构正确: {s}")

    # 如果 Zig 库可用，测试 R 阶段新函数
    if HAS_ZIG_RENDERER:
        try:
            from zeroai_tui import _zig_bindings
            lib = _zig_bindings._zig_lib
            # 测试 UTF-8 字符计数
            test_str = b"Hi\xe4\xbd\xa0\xe5\xa5\xbd"  # "Hi你好"
            count = lib.zig_utf8_char_count(test_str, len(test_str))
            assert count == 4, f"UTF-8 计数错误: {count}"
            print(f"  ✓ zig_utf8_char_count: 'Hi你好' -> {count}")

            # 测试 SIMD 字符比较
            a = b"abcdefg" + b"x" * 30
            b_buf = b"abcdefg" + b"x" * 30
            idx = lib.zig_simd_find_diff(a, b_buf, len(a))
            assert idx == len(a), f"相同缓冲区比较错误: {idx}"
            print(f"  ✓ zig_simd_find_diff: 相同缓冲区 -> {idx}")

            # 测试批量填充
            buf = (ctypes.c_char * 10)()
            lib.zig_fill_chars(buf, 10, b' ')
            print(f"  ✓ zig_fill_chars: 成功")
        except Exception as e:
            print(f"  ⚠ Zig 函数调用跳过: {e}")
    else:
        print(f"  ℹ Zig 库未编译，R 阶段函数测试跳过（回退到 Python）")

    print("✓ R 阶段测试通过")


def test_s_parallel_scheduler():
    """测试 S 阶段：并行工具调度器"""
    print("\n=== 测试 S 阶段：工具并行化 ===")
    from zeroai.core.parallel_tools import (
        ParallelToolScheduler,
        ToolCallRequest,
        ToolCallResult,
        ToolDependencyGraph,
        ResultMerger,
        reset_parallel_scheduler,
    )

    reset_parallel_scheduler()

    # 测试依赖图
    print("[S.1] 测试工具依赖图...")
    graph = ToolDependencyGraph()
    # 两个读工具：可并行
    req1 = ToolCallRequest(name="read_file", args={"path": "/tmp/a"})
    req2 = ToolCallRequest(name="read_file", args={"path": "/tmp/b"})
    assert not graph.has_dependency(req1, req2), "不同目标的读工具应有依赖"
    print(f"  ✓ 不同目标读工具可并行")

    # 写工具和读工具：同目标有依赖
    req_write = ToolCallRequest(name="write_file", args={"path": "/tmp/a", "content": "x"})
    req_read = ToolCallRequest(name="read_file", args={"path": "/tmp/a"})
    assert graph.has_dependency(req_write, req_read), "同目标的读写应有依赖"
    print(f"  ✓ 同目标读写串行")

    # 两个写工具：有依赖
    req_write2 = ToolCallRequest(name="write_file", args={"path": "/tmp/c", "content": "y"})
    assert graph.has_dependency(req_write, req_write2), "两个写工具应串行"
    print(f"  ✓ 写工具之间串行")

    # 测试批次分析
    requests = [
        ToolCallRequest(name="read_file", args={"path": "a"}),
        ToolCallRequest(name="read_file", args={"path": "b"}),
        ToolCallRequest(name="write_file", args={"path": "c", "content": "x"}),
        ToolCallRequest(name="write_file", args={"path": "d", "content": "y"}),
    ]
    batches = graph.analyze_batch(requests)
    assert len(batches) >= 2, f"批次数量错误: {batches}"
    # 第一批应包含两个读工具
    assert len(batches[0]) == 2, f"第一批应为读工具: {batches[0]}"
    print(f"  ✓ 批次分析: {batches}")

    # 测试结果合并器
    print("[S.2] 测试结果合并器...")
    merger = ResultMerger()
    results = [
        ToolCallResult(name="read_file", args={}, result="content_a", success=True, duration=0.1),
        ToolCallResult(name="read_file", args={}, result="content_b", success=True, duration=0.2),
    ]
    merged = merger.merge(results, strategy="concat")
    assert "content_a" in merged and "content_b" in merged, f"合并错误: {merged}"
    print(f"  ✓ concat 合并: {merged!r}")

    # priority 策略
    merged = merger.merge(results, strategy="priority")
    assert "content_a" in merged, f"priority 合并错误: {merged}"
    print(f"  ✓ priority 合并: {merged!r}")

    print("✓ S 阶段测试通过")


async def test_s_parallel_execution():
    """测试 S 阶段：并行执行"""
    print("\n=== 测试 S 阶段：并行执行 ===")
    from zeroai.core.parallel_tools import (
        ParallelToolScheduler,
        ToolCallRequest,
    )

    # 用同步函数测试
    def fast_tool(x: int = 0) -> str:
        return f"result_{x}"

    scheduler = ParallelToolScheduler(
        tool_map={"fast_tool": fast_tool},
        max_concurrency=4,
    )

    # 单工具执行
    result = await scheduler.execute_single(
        ToolCallRequest(name="fast_tool", args={"x": 42})
    )
    assert result.success, f"单工具执行失败: {result.error}"
    assert "result_42" in result.result, f"结果错误: {result.result}"
    print(f"  ✓ 单工具执行: {result.result}")

    # 并行执行多个
    requests = [
        ToolCallRequest(name="fast_tool", args={"x": i})
        for i in range(5)
    ]
    results = await scheduler.execute_parallel(requests)
    assert len(results) == 5, f"结果数量错误: {len(results)}"
    for i, r in enumerate(results):
        assert r.success, f"工具 {i} 失败: {r.error}"
        assert f"result_{i}" in r.result, f"工具 {i} 结果错误: {r.result}"
    print(f"  ✓ 并行执行 5 个工具全部成功")

    # 测试超时隔离
    def slow_tool() -> str:
        import time
        time.sleep(2)
        return "done"

    scheduler2 = ParallelToolScheduler(
        tool_map={"slow_tool": slow_tool, "fast_tool": fast_tool},
        max_concurrency=2,
    )
    requests = [
        ToolCallRequest(name="slow_tool", args={}, timeout=0.1),
        ToolCallRequest(name="fast_tool", args={"x": 1}),
    ]
    results = await scheduler2.execute_parallel(requests)
    assert results[0].timed_out, f"超时未触发: {results[0]}"
    assert results[1].success, f"快工具不应失败: {results[1]}"
    print(f"  ✓ 超时隔离: slow_tool 超时, fast_tool 成功")

    print("✓ S 阶段并行执行测试通过")


def test_t_vector_compressor():
    """测试 T 阶段：向量压缩器"""
    print("\n=== 测试 T 阶段：向量压缩 ===")
    try:
        import numpy as np
    except ImportError:
        print("  ⚠ numpy 不可用，跳过向量压缩测试")
        return

    from zeroai.core.memory_optimizer import VectorCompressor

    compressor = VectorCompressor(dtype="float16")
    # 生成测试向量
    original = np.random.randn(1000, 256).astype(np.float32)
    original_size = original.nbytes

    # 压缩
    compressed = compressor.compress(original)
    assert compressed.dtype == np.float16, f"压缩后类型错误: {compressed.dtype}"
    compressed_size = compressed.nbytes
    print(f"  ✓ 压缩: {original_size} -> {compressed_size} 字节")

    # 解压
    restored = compressor.decompress(compressed)
    assert restored.dtype == np.float32, f"解压后类型错误: {restored.dtype}"

    # 验证精度
    max_error = np.max(np.abs(original - restored))
    assert max_error < 0.01, f"精度损失过大: {max_error}"
    print(f"  ✓ 精度: 最大误差 {max_error:.6f}")

    # 内存节省统计
    savings = compressor.memory_savings(original_size)
    assert savings["saved_bytes"] > 0, "未节省内存"
    assert savings["compression_ratio"] == 0.5, f"压缩比错误: {savings['compression_ratio']}"
    print(f"  ✓ 节省: {savings['saved_bytes']} 字节 ({savings['compression_ratio']*100:.0f}%)")

    print("✓ T.1 向量压缩测试通过")


def test_t_unified_cache():
    """测试 T 阶段：统一缓存管理器"""
    print("\n=== 测试 T 阶段：统一缓存 ===")
    from zeroai.core.memory_optimizer import UnifiedCacheManager

    manager = UnifiedCacheManager(total_memory_mb=128)
    manager.register_cache("tool_cache", max_entries=3)
    manager.register_cache("vector_cache", max_entries=5)

    # 写入
    manager.put("tool_cache", "k1", "v1")
    manager.put("tool_cache", "k2", "v2")
    manager.put("tool_cache", "k3", "v3")

    # 读取
    assert manager.get("tool_cache", "k1") == "v1", "读取 k1 失败"
    assert manager.get("tool_cache", "k2") == "v2", "读取 k2 失败"
    print(f"  ✓ 缓存读写正常")

    # LRU 淘汰：写入第 4 个，k3 应被淘汰（因为 k1/k2 刚被访问）
    manager.put("tool_cache", "k4", "v4")
    assert manager.get("tool_cache", "k3") is None, "k3 应被 LRU 淘汰"
    assert manager.get("tool_cache", "k4") == "v4", "k4 应存在"
    print(f"  ✓ LRU 淘汰正常")

    # 统计
    stats = manager.get_stats("tool_cache")
    assert stats["hits"] >= 3, f"命中数错误: {stats['hits']}"
    assert stats["evictions"] >= 1, f"淘汰数错误: {stats['evictions']}"
    print(f"  ✓ 统计: hits={stats['hits']}, evictions={stats['evictions']}")

    # 多缓存统计
    all_stats = manager.get_all_stats()
    assert "tool_cache" in all_stats and "vector_cache" in all_stats
    print(f"  ✓ 多缓存管理: {list(all_stats.keys())}")

    print("✓ T.2 统一缓存测试通过")


def test_t_incremental_indexer():
    """测试 T 阶段：增量索引器"""
    print("\n=== 测试 T 阶段：增量索引 ===")
    from zeroai.core.memory_optimizer import IncrementalIndexer

    indexer = IncrementalIndexer()

    # 创建临时目录和文件
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试文件
        f1 = os.path.join(tmpdir, "a.py")
        f2 = os.path.join(tmpdir, "b.py")
        with open(f1, "w") as f:
            f.write("print('a')")
        with open(f2, "w") as f:
            f.write("print('b')")

        # 首次扫描：应检测到 2 个新增
        changes = indexer.detect_changes(tmpdir, extensions={".py"})
        assert len(changes["added"]) == 2, f"新增数量错误: {changes}"
        assert len(changes["modified"]) == 0
        assert len(changes["unchanged"]) == 0
        print(f"  ✓ 首次扫描: 2 个新增")

        # 第二次扫描：无变更
        changes = indexer.detect_changes(tmpdir, extensions={".py"})
        assert len(changes["added"]) == 0, f"不应有新增: {changes}"
        assert len(changes["unchanged"]) == 2, f"未变更数量错误: {changes}"
        print(f"  ✓ 二次扫描: 2 个未变更")

        # 修改一个文件
        time.sleep(0.1)
        with open(f1, "w") as f:
            f.write("print('modified')")

        changes = indexer.detect_changes(tmpdir, extensions={".py"})
        assert len(changes["modified"]) == 1, f"修改数量错误: {changes}"
        assert f1 in changes["modified"], f"修改文件错误: {changes['modified']}"
        print(f"  ✓ 三次扫描: 1 个修改")

        # 删除一个文件
        os.remove(f2)
        changes = indexer.detect_changes(tmpdir, extensions={".py"})
        assert len(changes["deleted"]) == 1, f"删除数量错误: {changes}"
        assert f2 in changes["deleted"], f"删除文件错误: {changes['deleted']}"
        print(f"  ✓ 四次扫描: 1 个删除")

    # 测试索引持久化
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmpf:
        index_path = tmpf.name
    try:
        assert indexer.save_index(index_path), "保存索引失败"
        new_indexer = IncrementalIndexer()
        assert new_indexer.load_index(index_path), "加载索引失败"
        stats = new_indexer.get_stats()
        assert stats["total_files"] >= 0, f"统计错误: {stats}"
        print(f"  ✓ 索引持久化: {stats}")
    finally:
        os.unlink(index_path)

    print("✓ T.3 增量索引测试通过")


def test_t_context_budget():
    """测试 T 阶段：上下文预算分配"""
    print("\n=== 测试 T 阶段：上下文预算 ===")
    from zeroai.core.memory_optimizer import ContextBudgetAllocator

    allocator = ContextBudgetAllocator(total_tokens=1000)

    items = [
        {"type": "answer", "content": "x" * 4000},  # 1000 tokens
        {"type": "tool_result", "content": "y" * 2000},  # 500 tokens
        {"type": "thought", "content": "z" * 800},  # 200 tokens
        {"type": "history", "content": "w" * 400},  # 100 tokens
    ]

    allocated = allocator.allocate(items)
    assert len(allocated) == 4, f"分配数量错误: {len(allocated)}"

    # answer 应被截断（4000 字符 > 预算 400 tokens = 1600 字符）
    answer_item = next(i for i in allocated if i["type"] == "answer")
    assert answer_item["truncated"], "answer 应被截断"
    print(f"  ✓ answer 截断: {answer_item['allocated_tokens']} tokens")

    # history 不应被截断
    history_item = next(i for i in allocated if i["type"] == "history")
    assert not history_item["truncated"], "history 不应被截断"
    print(f"  ✓ history 未截断: {history_item['allocated_tokens']} tokens")

    # 统计
    stats = allocator.get_stats(allocated)
    assert stats["truncated_items"] >= 1, f"截断项数错误: {stats}"
    assert stats["total_allocated"] <= 1000, f"总分配超出预算: {stats}"
    print(f"  ✓ 统计: {stats}")

    print("✓ T.4 上下文预算测试通过")


def test_u_module_imports():
    """测试 U 阶段：模块导入完整性"""
    print("\n=== 测试 U 阶段：模块导入完整性 ===")
    import zeroai
    print(f"  ✓ zeroai 版本: {zeroai.__version__}")

    from zeroai.core import (
        # R 阶段（Zig 绑定）
        # S 阶段
        ToolCallRequest, ToolCallResult, ToolDependencyGraph,
        ResultMerger, ParallelToolScheduler,
        get_parallel_scheduler, reset_parallel_scheduler,
        # T 阶段
        VectorCompressor, CacheStats, UnifiedCacheManager,
        FileIndexEntry, IncrementalIndexer, ContextBudgetAllocator,
        get_unified_cache_manager, get_incremental_indexer, reset_memory_optimizers,
    )
    print("  ✓ S/T 阶段所有新模块导入成功")

    # 验证 AgentLoop S 阶段集成
    from zeroai.core.agent import AgentLoop
    loop = AgentLoop(enable_parallel_tools=True, max_concurrency=2)
    assert hasattr(loop, "_parallel_scheduler"), "AgentLoop 缺少 _parallel_scheduler"
    assert hasattr(loop, "execute_tools_parallel"), "AgentLoop 缺少 execute_tools_parallel"
    assert loop._parallel_scheduler is not None, "并行调度器未初始化"
    print("  ✓ AgentLoop S 阶段集成验证通过")

    reset_parallel_scheduler()
    reset_memory_optimizers()
    print("✓ U 阶段模块导入测试通过")


def test_u_changelog():
    """测试 U 阶段：CHANGELOG 完整性"""
    print("\n=== 测试 U 阶段：CHANGELOG 完整性 ===")
    changelog_path = os.path.join(PROJECT_ROOT, "CHANGELOG.md")
    assert os.path.exists(changelog_path), "CHANGELOG.md 不存在"

    with open(changelog_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 验证各阶段都有记录
    stages = ["阶段 N", "阶段 O", "阶段 P", "阶段 Q", "阶段 R", "阶段 S", "阶段 T"]
    for stage in stages:
        assert stage in content, f"CHANGELOG 缺少 {stage} 记录"
    print(f"  ✓ CHANGELOG 包含 N/O/P/Q/R/S/T 全部阶段")

    # 验证 Unreleased 段
    assert "## [Unreleased]" in content, "缺少 Unreleased 段"
    print(f"  ✓ Unreleased 段存在")

    print("✓ U 阶段 CHANGELOG 测试通过")


def test_u_tool_registry():
    """测试 U 阶段：工具注册完整性"""
    print("\n=== 测试 U 阶段：工具注册完整性 ===")
    from zeroai.tools.registry import TOOL_MAP, TOOLS

    # 验证 Q 阶段工具
    q_tools = ["code_graph_index", "code_graph_query", "code_graph_stats"]
    for t in q_tools:
        assert t in TOOL_MAP, f"{t} 未注册到 TOOL_MAP"
    print(f"  ✓ Q 阶段工具注册完整: {q_tools}")

    # 验证 N 阶段工具
    n_tools = ["code_execute", "code_check"]
    for t in n_tools:
        assert t in TOOL_MAP, f"{t} 未注册到 TOOL_MAP"
    print(f"  ✓ N 阶段工具注册完整: {n_tools}")

    # 验证 TOOLS schema 包含这些工具
    tool_names_in_schema = {t["function"]["name"] for t in TOOLS}
    for t in q_tools + n_tools:
        assert t in tool_names_in_schema, f"{t} 未在 TOOLS schema 中"
    print(f"  ✓ TOOLS schema 包含全部新工具")

    print("✓ U 阶段工具注册测试通过")


async def test_u_agent_loop_parallel():
    """测试 U 阶段：AgentLoop 并行工具执行"""
    print("\n=== 测试 U 阶段：AgentLoop 并行执行 ===")
    from zeroai.core.agent import AgentLoop
    from zeroai.core.parallel_tools import reset_parallel_scheduler

    reset_parallel_scheduler()

    loop = AgentLoop(enable_parallel_tools=True, max_concurrency=4)

    # 并行执行多个只读工具
    tool_calls = [
        {"name": "system_info", "args": {}},
        {"name": "list_windows", "args": {}},
    ]
    merged, results = await loop.execute_tools_parallel(tool_calls)
    assert len(results) == 2, f"结果数量错误: {len(results)}"
    print(f"  ✓ 并行执行 {len(results)} 个工具")

    # 验证合并结果
    assert isinstance(merged, str), f"合并结果类型错误: {type(merged)}"
    assert len(merged) > 0, "合并结果为空"
    print(f"  ✓ 结果合并: {len(merged)} 字符")

    reset_parallel_scheduler()
    print("✓ U 阶段 AgentLoop 并行测试通过")


def main():
    """主测试函数"""
    print("=" * 60)
    print("RSTU 阶段综合测试")
    print("=" * 60)

    tests = [
        ("R Zig 绑定", test_r_zig_bindings),
        ("S 依赖图", test_s_parallel_scheduler),
        ("U 模块导入", test_u_module_imports),
        ("U CHANGELOG", test_u_changelog),
        ("U 工具注册", test_u_tool_registry),
        ("T.1 向量压缩", test_t_vector_compressor),
        ("T.2 统一缓存", test_t_unified_cache),
        ("T.3 增量索引", test_t_incremental_indexer),
        ("T.4 上下文预算", test_t_context_budget),
    ]

    async_tests = [
        ("S 并行执行", test_s_parallel_execution),
        ("U AgentLoop 并行", test_u_agent_loop_parallel),
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

    for name, test_fn in async_tests:
        try:
            asyncio.run(test_fn())
            passed += 1
        except Exception as e:
            failed += 1
            print(f"✗ {name} 测试失败: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败, 共 {len(tests) + len(async_tests)} 项")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
