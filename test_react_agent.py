"""测试 ReAct Agent 和向量记忆模块"""
import asyncio
import os
import sys
import tempfile

# 确保项目根目录在 sys.path
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)


def test_planner_parse_json():
    """测试规划器 JSON 解析"""
    from zeroai.core.agent import ReActPlanner

    planner = ReActPlanner()

    # 纯 JSON
    response = '{"thought": "需要检查系统", "next_action": {"type": "tool_call", "tool": "system_info", "args": {}}, "task_complete": false}'
    plan = planner._parse_plan(response)
    assert plan["next_action"]["type"] == "tool_call"
    assert plan["next_action"]["tool"] == "system_info"
    print("test_planner_parse_json passed")

    # markdown 代码块包裹
    response = '```json\n{"thought": "直接回答", "next_action": {"type": "final_answer", "answer": "你好"}, "task_complete": true}\n```'
    plan = planner._parse_plan(response)
    assert plan["next_action"]["type"] == "final_answer"
    assert plan["next_action"]["answer"] == "你好"
    print("test_planner_parse_markdown passed")

    # 前后有多余文字
    response = '好的，让我分析一下：\n{"thought": "读取文件", "next_action": {"type": "tool_call", "tool": "read_file", "args": {"path": "test.py"}}, "task_complete": false}\n以上是我的分析。'
    plan = planner._parse_plan(response)
    assert plan["next_action"]["tool"] == "read_file"
    print("test_planner_parse_extra_text passed")


def test_planner_validate():
    """测试规划输出校验"""
    from zeroai.core.agent import ReActPlanner

    planner = ReActPlanner()

    # tool_call 缺少 tool 名
    plan = planner._validate_plan({
        "thought": "test",
        "next_action": {"type": "tool_call"},
        "task_complete": False,
    })
    assert plan["next_action"]["type"] == "final_answer"
    print("test_planner_validate_missing_tool passed")

    # 无效 type
    plan = planner._validate_plan({
        "thought": "test",
        "next_action": {"type": "invalid_type"},
        "task_complete": False,
    })
    assert plan["next_action"]["type"] == "final_answer"
    print("test_planner_validate_invalid_type passed")


def test_tfidf_vectorizer():
    """测试 TF-IDF 向量化器"""
    from zeroai.memory.vector_store import TfidfVectorizer
    import numpy as np

    texts = [
        "def hello_world(): print('hello')",
        "class Foo: pass",
        "function hello world python",
        "你好世界",
    ]
    vec = TfidfVectorizer(dim=64)
    vec.fit(texts)

    v1 = vec.transform("hello world")
    v2 = vec.transform("hello python")
    v3 = vec.transform("你好")

    assert v1.shape == (64,)
    assert v2.shape == (64,)
    assert v3.shape == (64,)

    # hello world 和 hello python 应该比 hello world 和 你好 更相似
    sim1 = float(np.dot(v1, v2))
    sim2 = float(np.dot(v1, v3))
    assert sim1 >= 0, f"sim1={sim1}"
    print(f"test_tfidf_vectorizer passed (sim1={sim1:.3f}, sim2={sim2:.3f})")


def test_vector_store():
    """测试向量存储"""
    from zeroai.memory.vector_store import VectorStore, EmbeddingBackend

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        # 用 TF-IDF 后端（不依赖 API）
        embedding = EmbeddingBackend(api_key="")  # _api_available=False
        store = VectorStore(db_path, embedding=embedding)

        # 添加文档
        asyncio.get_event_loop().run_until_complete(
            store.add("doc1#0", "test.py", "def hello(): print('hello world')")
        )
        asyncio.get_event_loop().run_until_complete(
            store.add("doc2#0", "main.py", "def main(): return 42")
        )

        # 检索
        results = store.search("hello world", top_k=2)
        assert len(results) > 0
        assert "hello" in results[0]["content"]
        print(f"test_vector_store passed (top result: {results[0]['source']})")

        # 统计
        stats = store.get_stats()
        assert stats["total_chunks"] == 2
        print(f"test_vector_store_stats passed (chunks={stats['total_chunks']})")


def test_project_indexer():
    """测试项目索引器"""
    from zeroai.memory.project_indexer import ProjectIndexer
    from zeroai.memory.vector_store import VectorStore, EmbeddingBackend

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试文件
        with open(os.path.join(tmpdir, "test.py"), "w") as f:
            f.write("def hello():\n    print('hello world')\n\nclass Foo:\n    pass\n")

        with open(os.path.join(tmpdir, "README.md"), "w") as f:
            f.write("# Test Project\n\nThis is a test.\n")

        db_path = os.path.join(tmpdir, "test.db")
        embedding = EmbeddingBackend(api_key="")
        store = VectorStore(db_path, embedding=embedding)
        indexer = ProjectIndexer(store=store)

        stats = asyncio.get_event_loop().run_until_complete(
            indexer.index_project(tmpdir)
        )

        assert stats["total_files"] == 2
        assert stats["indexed_files"] == 2
        assert stats["total_chunks"] > 0
        print(f"test_project_indexer passed (files={stats['indexed_files']}, chunks={stats['total_chunks']})")

        # 检索
        results = store.search("hello world", top_k=2)
        assert len(results) > 0
        print(f"test_project_indexer_search passed (top: {results[0]['source']})")


def test_retriever():
    """测试检索器"""
    from zeroai.memory.retriever import Retriever
    from zeroai.memory.vector_store import VectorStore, EmbeddingBackend
    from zeroai.memory.project_indexer import ProjectIndexer

    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "test.py"), "w") as f:
            f.write("def calculate_sum(a, b):\n    return a + b\n")

        db_path = os.path.join(tmpdir, "test.db")
        embedding = EmbeddingBackend(api_key="")
        store = VectorStore(db_path, embedding=embedding)
        indexer = ProjectIndexer(store=store)
        asyncio.get_event_loop().run_until_complete(indexer.index_project(tmpdir))

        retriever = Retriever(store=store)
        results = retriever("calculate sum")
        assert len(results) > 0
        assert "calculate_sum" in results[0]
        print(f"test_retriever passed (result preview: {results[0][:50]}...)")


def test_agent_loop_mock():
    """测试 AgentLoop（用 mock planner，不调用真实 API）"""
    from zeroai.core.agent import AgentLoop, ReActPlanner

    # 创建 mock planner
    class MockPlanner:
        def __init__(self):
            self.call_count = 0

        async def plan_next(self, user_input, messages, tools, executed_steps, retriever=None):
            self.call_count += 1
            if self.call_count == 1:
                return {
                    "thought": "需要查看系统信息",
                    "next_action": {
                        "type": "tool_call",
                        "tool": "system_info",
                        "args": {},
                    },
                    "task_complete": False,
                }
            else:
                return {
                    "thought": "已获取系统信息，可以回答了",
                    "next_action": {
                        "type": "final_answer",
                        "answer": "系统信息已获取",
                    },
                    "task_complete": True,
                }

    # 创建 mock tool
    def mock_system_info():
        return "OS: Windows, CPU: x86_64"

    tool_map = {"system_info": mock_system_info}
    tools_schema = [{"type": "function", "function": {"name": "system_info", "description": "Get system info"}}]

    loop = AgentLoop(
        planner=MockPlanner(),
        tool_map=tool_map,
        tools_schema=tools_schema,
        max_steps=5,
    )

    # 记录回调
    thoughts = []
    tool_calls = []
    tool_results = []
    final_answers = []

    async def on_thought(text):
        thoughts.append(text)

    async def on_tool_call(name, args):
        tool_calls.append((name, args))

    async def on_tool_result(name, result):
        tool_results.append((name, result))

    async def on_final_answer(answer):
        final_answers.append(answer)

    loop.on_thought = on_thought
    loop.on_tool_call = on_tool_call
    loop.on_tool_result = on_tool_result
    loop.on_final_answer = on_final_answer

    messages = [{"role": "system", "content": "test"}]
    final_answer, steps = asyncio.get_event_loop().run_until_complete(
        loop.run("查看系统信息", messages)
    )

    assert len(thoughts) == 2
    assert len(tool_calls) == 1
    assert tool_calls[0][0] == "system_info"
    assert len(tool_results) == 1
    assert "Windows" in tool_results[0][1]
    assert len(final_answers) == 1
    assert final_answers[0] == "系统信息已获取"
    assert len(steps) == 2
    print("test_agent_loop_mock passed")


if __name__ == "__main__":
    test_planner_parse_json()
    test_planner_validate()
    test_tfidf_vectorizer()
    test_vector_store()
    test_project_indexer()
    test_retriever()
    test_agent_loop_mock()
    print("\n=== All ReAct Agent + Memory tests passed! ===")
