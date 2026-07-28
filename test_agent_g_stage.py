"""G 阶段 Agent Loop 优化测试"""
import sys
import os
import asyncio
import tempfile
import time
from pathlib import Path

sys.path.insert(0, r"d:\C\C")

from zeroai.core.agent_persistence import (
    ThoughtSnapshot,
    AgentSession,
    AgentPersistence,
    list_sessions,
    get_session_by_task,
    cleanup_old_sessions,
)
from zeroai.core.tool_cache import (
    CacheEntry,
    ToolResultCache,
    get_tool_cache,
    reset_tool_cache,
)
from zeroai.core.thought_visualizer import (
    ThoughtVisualizer,
    render_thought_card,
    render_thought_chain,
    Color,
)


# ============================================================================
# G.2 持久化测试
# ============================================================================

def test_thought_snapshot():
    """G.2: ThoughtSnapshot 数据结构"""
    print("[G.2.1] ThoughtSnapshot creation...")
    snapshot = ThoughtSnapshot(
        step=1,
        thought="需要读取文件",
        action_type="tool_call",
        tool_name="read_file",
        args={"path": "/tmp/test.txt"},
        result="file content",
        success=True,
        timestamp=time.time(),
    )
    assert snapshot.step == 1
    assert snapshot.tool_name == "read_file"
    assert snapshot.success is True

    d = snapshot.to_dict()
    assert d["step"] == 1
    assert d["tool_name"] == "read_file"

    # 反序列化
    snapshot2 = ThoughtSnapshot.from_dict(d)
    assert snapshot2.step == 1
    assert snapshot2.tool_name == "read_file"
    print("  [OK] ThoughtSnapshot serialization")
    return True


def test_persistence_save_load():
    """G.2: 持久化保存和加载"""
    print("[G.2.2] Persistence save/load...")
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = AgentPersistence(
            session_id="test_session_001",
            storage_dir=Path(tmpdir),
        )

        # 创建思维链
        chain = [
            ThoughtSnapshot(step=1, thought="第一步", action_type="tool_call", tool_name="read_file"),
            ThoughtSnapshot(step=2, thought="第二步", action_type="final_answer"),
        ]
        messages = [
            {"role": "user", "content": "测试任务"},
            {"role": "assistant", "content": "执行中"},
        ]

        # 保存
        success = persistence.save_chain(
            thought_chain=chain,
            messages=messages,
            task="测试任务",
            is_paused=True,
        )
        assert success
        assert persistence.session_file.exists()

        # 加载
        session = persistence.load_chain()
        assert session is not None
        assert session.session_id == "test_session_001"
        assert session.task == "测试任务"
        assert len(session.thought_chain) == 2
        assert session.thought_chain[0].step == 1
        assert session.thought_chain[1].step == 2
        assert session.is_paused is True
        print("  [OK] Save/load roundtrip")
    return True


def test_persistence_append():
    """G.2: 增量追加思维节点"""
    print("[G.2.3] Incremental append...")
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = AgentPersistence(
            session_id="test_session_002",
            storage_dir=Path(tmpdir),
        )

        # 第一次追加
        t1 = ThoughtSnapshot(step=1, thought="开始", action_type="plan")
        persistence.append_thought(t1, messages=[{"role": "user", "content": "hi"}])

        # 第二次追加
        t2 = ThoughtSnapshot(step=2, thought="执行", action_type="tool_call", tool_name="search")
        persistence.append_thought(t2)

        # 加载验证
        session = persistence.load_chain()
        assert session is not None
        assert len(session.thought_chain) == 2
        assert session.thought_chain[1].tool_name == "search"
        print("  [OK] Incremental append")
    return True


def test_resume_point():
    """G.2: 断点续跑点查询"""
    print("[G.2.4] Resume point...")
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = AgentPersistence(
            session_id="test_session_003",
            storage_dir=Path(tmpdir),
        )

        chain = [
            ThoughtSnapshot(step=1, thought="第一步", action_type="tool_call"),
            ThoughtSnapshot(step=2, thought="第二步", action_type="tool_call"),
        ]
        persistence.save_chain(chain, [{"role": "user", "content": "task"}], task="未完成任务", is_paused=True)

        # 获取续跑点
        resume = persistence.get_resume_point()
        assert resume is not None
        assert resume["session_id"] == "test_session_003"
        assert resume["completed_steps"] == 2
        assert resume["is_paused"] is True
        assert resume["last_thought"]["step"] == 2

        # 标记完成后再查
        persistence.mark_completed("最终答案")
        resume2 = persistence.get_resume_point()
        assert resume2 is None  # 已完成的不返回续跑点
        print("  [OK] Resume point detection")
    return True


def test_list_sessions():
    """G.2: 会话列表查询"""
    print("[G.2.5] List sessions...")
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建多个会话
        for i in range(3):
            p = AgentPersistence(
                session_id=f"list_test_{i}",
                storage_dir=Path(tmpdir),
            )
            p.save_chain(
                [ThoughtSnapshot(step=1, thought=f"task_{i}", action_type="plan")],
                [{"role": "user", "content": f"task_{i}"}],
                task=f"任务_{i}",
            )

        sessions = list_sessions(Path(tmpdir))
        assert len(sessions) == 3
        # 验证按更新时间倒序
        for s in sessions:
            assert "session_id" in s
            assert "task" in s
            assert "steps" in s

        # 按任务关键词查找
        found = get_session_by_task("任务_1", Path(tmpdir))
        assert found == "list_test_1"
        print("  [OK] Session listing and search")
    return True


def test_cleanup_old_sessions():
    """G.2: 清理过期会话"""
    print("[G.2.6] Cleanup old sessions...")
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建一个旧会话（修改时间为 60 天前）
        p = AgentPersistence(
            session_id="old_session",
            storage_dir=Path(tmpdir),
        )
        p.save_chain(
            [ThoughtSnapshot(step=1, thought="old", action_type="plan")],
            [{"role": "user", "content": "old"}],
        )

        # 修改文件时间为 60 天前
        import os
        old_time = time.time() - 60 * 86400
        os.utime(p.session_file, (old_time, old_time))

        # 创建一个新会话
        p2 = AgentPersistence(
            session_id="new_session",
            storage_dir=Path(tmpdir),
        )
        p2.save_chain(
            [ThoughtSnapshot(step=1, thought="new", action_type="plan")],
            [{"role": "user", "content": "new"}],
        )

        # 清理 30 天前的会话
        count = cleanup_old_sessions(max_age_days=30, storage_dir=Path(tmpdir))
        assert count == 1  # 只清理旧会话

        sessions = list_sessions(Path(tmpdir))
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "new_session"
        print("  [OK] Cleanup removed 1 old session")
    return True


# ============================================================================
# G.3 工具缓存测试
# ============================================================================

def test_tool_cache_basic():
    """G.3: 工具缓存基本功能"""
    print("[G.3.1] Tool cache basic...")
    reset_tool_cache()
    cache = get_tool_cache(max_entries=10, ttl_seconds=60)

    call_count = 0

    def fake_tool(path: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"content of {path}"

    async def run():
        # 第一次调用：miss
        result1 = await cache.call_with_cache("read_file", {"path": "/a"}, fake_tool)
        assert result1 == "content of /a"
        assert call_count == 1

        # 第二次相同调用：hit
        result2 = await cache.call_with_cache("read_file", {"path": "/a"}, fake_tool)
        assert result2 == "content of /a"
        assert call_count == 1  # 没有再次调用

        # 不同参数：miss
        result3 = await cache.call_with_cache("read_file", {"path": "/b"}, fake_tool)
        assert result3 == "content of /b"
        assert call_count == 2

    asyncio.run(run())

    stats = cache.get_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 2
    assert stats["hit_rate"] > 0
    print(f"  [OK] Cache: hits={stats['hits']}, misses={stats['misses']}")
    return True


def test_tool_cache_no_cache_tools():
    """G.3: 不缓存工具"""
    print("[G.3.2] No-cache tools...")
    reset_tool_cache()
    cache = get_tool_cache()

    call_count = 0

    def get_time() -> str:
        nonlocal call_count
        call_count += 1
        return str(time.time())

    async def run():
        # get_time 默认不缓存
        await cache.call_with_cache("get_time", {}, get_time)
        await cache.call_with_cache("get_time", {}, get_time)
        assert call_count == 2  # 两次都实际调用

    asyncio.run(run())
    stats = cache.get_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0  # 不缓存的工具不记 miss
    print("  [OK] get_time not cached (2 calls)")
    return True


def test_tool_cache_force_refresh():
    """G.3: 强制刷新缓存"""
    print("[G.3.3] Force refresh...")
    reset_tool_cache()
    cache = get_tool_cache()

    call_count = 0

    def fake_tool(p: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"v{call_count}"

    async def run():
        await cache.call_with_cache("read", {"p": "/x"}, fake_tool)
        await cache.call_with_cache("read", {"p": "/x"}, fake_tool)  # hit
        await cache.call_with_cache("read", {"p": "/x"}, fake_tool, force_refresh=True)  # miss

    asyncio.run(run())
    # 第一次调用 + 强制刷新 = 2 次实际调用
    assert call_count == 2, f"Expected 2 calls, got {call_count}"
    stats = cache.get_stats()
    assert stats["hits"] == 1, f"Expected 1 hit, got {stats['hits']}"
    print(f"  [OK] Force refresh: {call_count} calls, {stats['hits']} hits")
    return True


def test_tool_cache_ttl():
    """G.3: TTL 过期"""
    print("[G.3.4] TTL expiration...")
    reset_tool_cache()
    cache = get_tool_cache(ttl_seconds=0.1)  # 0.1 秒 TTL

    call_count = 0

    def fake_tool() -> str:
        nonlocal call_count
        call_count += 1
        return f"result_{call_count}"

    async def run():
        await cache.call_with_cache("test", {}, fake_tool)
        await asyncio.sleep(0.15)  # 等待过期
        await cache.call_with_cache("test", {}, fake_tool)

    asyncio.run(run())
    assert call_count == 2  # 过期后重新调用
    print("  [OK] TTL expired, re-called")
    return True


def test_tool_cache_lru_eviction():
    """G.3: LRU 淘汰"""
    print("[G.3.5] LRU eviction...")
    reset_tool_cache()
    cache = get_tool_cache(max_entries=3)  # 只缓存 3 条

    call_count = 0

    def fake_tool(key: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"v_{key}"

    async def run():
        # 填满缓存
        for i in range(3):
            await cache.call_with_cache("tool", {"key": f"k{i}"}, fake_tool)
        assert call_count == 3

        # 访问 k0，使其成为最近使用
        await cache.call_with_cache("tool", {"key": "k0"}, fake_tool)
        assert call_count == 3  # hit

        # 添加 k3，应该淘汰 k1（LRU）
        await cache.call_with_cache("tool", {"key": "k3"}, fake_tool)
        assert call_count == 4

        # k0 应该还在（最近访问过）
        await cache.call_with_cache("tool", {"key": "k0"}, fake_tool)
        assert call_count == 4  # hit

    asyncio.run(run())
    stats = cache.get_stats()
    assert stats["evictions"] >= 1
    print(f"  [OK] LRU evicted {stats['evictions']} entries")
    return True


# ============================================================================
# G.1 思维链可视化测试
# ============================================================================

def test_visualizer_card():
    """G.1: 思维卡片渲染"""
    print("[G.1.1] Thought card rendering...")
    viz = ThoughtVisualizer(width=60)

    thought = ThoughtSnapshot(
        step=1,
        thought="需要读取配置文件",
        action_type="tool_call",
        tool_name="read_file",
        args={"path": "/etc/config.json"},
        result='{"key": "value"}',
        success=True,
        timestamp=time.time(),
    )

    card = viz.render_card(thought)
    assert "步骤 1" in card
    assert "tool_call" in card
    assert "read_file" in card
    assert "[OK]" in card
    assert "=" in card  # 边框
    print("  [OK] Card rendered with borders and icons")
    return True


def test_visualizer_chain():
    """G.1: 思维链渲染"""
    print("[G.1.2] Thought chain rendering...")
    viz = ThoughtVisualizer(width=60)

    chain = [
        ThoughtSnapshot(step=1, thought="分析任务", action_type="plan"),
        ThoughtSnapshot(step=2, thought="读取文件", action_type="tool_call", tool_name="read_file", success=True),
        ThoughtSnapshot(step=3, thought="处理失败", action_type="tool_call", tool_name="write_file", success=False, result="Permission denied"),
        ThoughtSnapshot(step=4, thought="给出答案", action_type="final_answer"),
    ]

    output = viz.render_chain(chain, show_progress=True)
    # 移除 ANSI 颜色码后检查内容
    import re
    plain = re.sub(r'\033\[[0-9;]*m', '', output)
    assert "思维链" in plain
    assert "4 步" in plain
    assert "进度" in plain
    assert "总结" in plain
    assert "成功: 3" in plain
    assert "失败: 1" in plain
    print("  [OK] Chain rendered with progress and summary")
    return True


def test_visualizer_colors():
    """G.1: 颜色编码"""
    print("[G.1.3] Color coding...")
    from zeroai.core.thought_visualizer import ACTION_COLORS, ACTION_ICONS

    assert "tool_call" in ACTION_COLORS
    assert "final_answer" in ACTION_COLORS
    assert "reflect" in ACTION_COLORS
    assert "plan" in ACTION_COLORS

    assert ACTION_COLORS["tool_call"] == Color.CYAN
    assert ACTION_COLORS["final_answer"] == Color.GREEN
    assert ACTION_COLORS["reflect"] == Color.MAGENTA

    assert ACTION_ICONS["tool_call"] == "[*]"
    assert ACTION_ICONS["final_answer"] == "[=]"
    print("  [OK] Color and icon mapping correct")
    return True


def test_visualizer_convenience():
    """G.1: 便捷函数"""
    print("[G.1.4] Convenience functions...")
    thought = ThoughtSnapshot(step=1, thought="test", action_type="plan")

    card = render_thought_card(thought, width=40)
    assert "步骤 1" in card

    chain_text = render_thought_chain([thought], width=40)
    assert "思维链" in chain_text
    print("  [OK] Convenience functions work")
    return True


def main():
    print("=" * 60)
    print("ZeroAI Agent Loop G-Stage Tests (G.1-G.3)")
    print("=" * 60)
    print()

    tests = [
        # G.2 持久化
        ("G.2.1 ThoughtSnapshot", test_thought_snapshot),
        ("G.2.2 Save/Load", test_persistence_save_load),
        ("G.2.3 Append", test_persistence_append),
        ("G.2.4 Resume Point", test_resume_point),
        ("G.2.5 List Sessions", test_list_sessions),
        ("G.2.6 Cleanup", test_cleanup_old_sessions),
        # G.3 缓存
        ("G.3.1 Cache Basic", test_tool_cache_basic),
        ("G.3.2 No-Cache Tools", test_tool_cache_no_cache_tools),
        ("G.3.3 Force Refresh", test_tool_cache_force_refresh),
        ("G.3.4 TTL", test_tool_cache_ttl),
        ("G.3.5 LRU Eviction", test_tool_cache_lru_eviction),
        # G.1 可视化
        ("G.1.1 Card", test_visualizer_card),
        ("G.1.2 Chain", test_visualizer_chain),
        ("G.1.3 Colors", test_visualizer_colors),
        ("G.1.4 Convenience", test_visualizer_convenience),
    ]

    passed = 0
    failed = 0
    for name, test in tests:
        print()
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
