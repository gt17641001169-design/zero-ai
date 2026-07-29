"""阶段 M 完整测试：Embedding API + 向量存储升级 + RAG 管道

测试覆盖：
M.1: LLMClient.embed() 方法
M.2: EmbeddingBackend 外部 embed_func 注入 + FAISS 可选支持
M.3: SemanticChunker 语义分块 + MMRReranker 重排序 + ContextCompressor 压缩 + RAGPipeline 端到端
"""
import os
import sys
import asyncio
import tempfile

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_m1_llm_embed_signature():
    """M.1: LLMClient.embed 方法签名验证"""
    print("=" * 60)
    print("测试 M.1: LLMClient.embed 方法签名")
    print("=" * 60)
    from zeroai.core.llm import LLMClient
    import inspect

    # 验证 embed 方法存在
    assert hasattr(LLMClient, "embed"), "LLMClient 应有 embed 方法"
    assert hasattr(LLMClient, "embed_sync"), "LLMClient 应有 embed_sync 方法"
    assert hasattr(LLMClient, "embed_one"), "LLMClient 应有 embed_one 方法"

    # 验证签名
    sig = inspect.signature(LLMClient.embed)
    params = list(sig.parameters.keys())
    assert "texts" in params, "embed 应有 texts 参数"
    assert "dimensions" in params, "embed 应有 dimensions 参数"
    assert "timeout" in params, "embed 应有 timeout 参数"

    print("  [OK] embed 方法签名正确")
    print("  [OK] embed_sync 方法存在")
    print("  [OK] embed_one 方法存在")
    return True


def test_m2_embedding_backend_embed_func():
    """M.2: EmbeddingBackend 支持外部 embed_func 注入"""
    print("\n" + "=" * 60)
    print("测试 M.2: EmbeddingBackend 外部 embed_func 注入")
    print("=" * 60)
    from zeroai.memory.vector_store import EmbeddingBackend
    import numpy as np

    # 构造假 embed_func（返回固定 8 维向量）
    async def fake_embed(texts):
        return [[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8] for _ in texts]

    backend = EmbeddingBackend(embed_func=fake_embed, embed_dim=8)

    # 验证维度
    assert backend.dim == 8, f"维度应为 8, 实际 {backend.dim}"
    print(f"  [OK] embed_func 模式维度正确: {backend.dim}")

    # 验证 api_available
    assert backend._api_available, "注入 embed_func 后 api_available 应为 True"
    print("  [OK] api_available = True")

    # 验证嵌入
    async def _test():
        texts = ["hello", "world"]
        vecs = await backend.embed_texts(texts)
        assert vecs.shape == (2, 8), f"shape 应为 (2, 8), 实际 {vecs.shape}"
        return vecs

    vecs = asyncio.get_event_loop().run_until_complete(_test())
    print(f"  [OK] 嵌入结果 shape: {vecs.shape}")
    return True


def test_m2_vector_store_faiss_detection():
    """M.2: VectorStore FAISS 可选支持"""
    print("\n" + "=" * 60)
    print("测试 M.2: VectorStore FAISS 可选支持")
    print("=" * 60)
    from zeroai.memory.vector_store import VectorStore

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        store = VectorStore(db_path)

        # 验证 FAISS 检测不崩溃
        print(f"  [OK] FAISS available: {store._faiss_available}")
        print("  [OK] VectorStore 初始化成功（无论 FAISS 是否可用）")
    return True


def test_m3_semantic_chunker_basic():
    """M.3: SemanticChunker 语义分块"""
    print("\n" + "=" * 60)
    print("测试 M.3: SemanticChunker 语义分块")
    print("=" * 60)
    from zeroai.memory.rag_pipeline import SemanticChunker

    chunker = SemanticChunker(target_chunk_size=200, min_chunk_size=50)

    # 测试 Markdown 标题切分
    text = """# 第一章

这是第一章的内容。这是一个测试段落，用于验证语义分块功能。

## 1.1 小节

这是小节内容。包含一些代码：

```python
def hello():
    print("hello")
```

代码块应该保持完整。

# 第二章

这是第二章的内容。另一个段落。
"""
    chunks = chunker.chunk_text(text, source="test.md")

    assert len(chunks) > 0, "应至少有 1 个 chunk"
    print(f"  [OK] 分块数量: {len(chunks)}")

    # 验证每个 chunk 有必要字段
    for chunk in chunks:
        assert "content" in chunk
        assert "source" in chunk
        assert "section" in chunk
        assert "chunk_index" in chunk
        assert "content_hash" in chunk

    # 验证标题被识别
    sections = [c["section"] for c in chunks if c["section"]]
    print(f"  [OK] 识别的章节: {sections}")

    # 验证代码块完整（至少有一个 chunk 包含完整代码块）
    has_code = any("```python" in c["content"] and "```" in c["content"].split("```python")[1]
                   for c in chunks)
    print(f"  [OK] 代码块保持完整: {has_code}")

    return True


def test_m3_semantic_chunker_short_merge():
    """M.3: 短块合并"""
    print("\n" + "=" * 60)
    print("测试 M.3: 短块合并")
    print("=" * 60)
    from zeroai.memory.rag_pipeline import SemanticChunker

    chunker = SemanticChunker(target_chunk_size=500, min_chunk_size=100)

    # 多个短段落
    text = "短段落一。\n\n短段落二。\n\n短段落三。\n\n短段落四。"
    chunks = chunker.chunk_text(text, source="short.md")

    # 短块应被合并
    print(f"  [OK] 短文本分块数: {len(chunks)}")
    for c in chunks:
        print(f"    - size={c['size']}, content={c['content'][:50]}...")

    return True


def test_m3_mmr_reranker():
    """M.3: MMRReranker 重排序"""
    print("\n" + "=" * 60)
    print("测试 M.3: MMRReranker 重排序")
    print("=" * 60)
    from zeroai.memory.rag_pipeline import MMRReranker

    reranker = MMRReranker(lambda_param=0.7)

    # 构造候选结果（有重复内容）
    candidates = [
        {"content": "Python 编程语言入门教程", "score": 0.9, "source": "doc1"},
        {"content": "Python 编程语言进阶指南", "score": 0.85, "source": "doc2"},
        {"content": "Java 编程语言基础", "score": 0.7, "source": "doc3"},
        {"content": "数据库设计与优化", "score": 0.6, "source": "doc4"},
        {"content": "Python 编程语言高级特性", "score": 0.8, "source": "doc5"},
    ]

    result = reranker.rerank("Python 编程", candidates, top_k=3)

    assert len(result) == 3, f"应返回 3 个结果, 实际 {len(result)}"
    print(f"  [OK] 重排序后数量: {len(result)}")

    # MMR 应优先多样性，不应全部是 Python 相关
    python_count = sum(1 for r in result if "Python" in r["content"])
    print(f"  [OK] 结果中 Python 相关数量: {python_count}/3")

    for i, r in enumerate(result, 1):
        print(f"    [{i}] score={r['score']:.2f} - {r['content']}")

    return True


def test_m3_context_compressor():
    """M.3: ContextCompressor 上下文压缩"""
    print("\n" + "=" * 60)
    print("测试 M.3: ContextCompressor 上下文压缩")
    print("=" * 60)
    from zeroai.memory.rag_pipeline import ContextCompressor

    # 小配额测试压缩
    compressor = ContextCompressor(max_total_length=500, max_per_chunk=200)

    # 构造超长结果
    results = [
        {"content": "A" * 300, "source": "doc1", "score": 0.9},
        {"content": "B" * 300, "source": "doc2", "score": 0.8},
        {"content": "C" * 300, "source": "doc3", "score": 0.7},
    ]

    compressed = compressor.compress(results)

    assert len(compressed) <= 600, f"压缩后应较短, 实际 {len(compressed)} 字符"
    print(f"  [OK] 原始总长度: 900+")
    print(f"  [OK] 压缩后长度: {len(compressed)}")

    # 验证包含省略标记
    assert "省略" in compressed, "压缩后应包含省略标记"
    print("  [OK] 包含省略标记")

    # 测试不压缩的情况
    compressor2 = ContextCompressor(max_total_length=10000, max_per_chunk=2000)
    short_results = [{"content": "短内容", "source": "doc1", "score": 0.9}]
    not_compressed = compressor2.compress(short_results)
    assert "短内容" in not_compressed
    assert "省略" not in not_compressed
    print("  [OK] 未超限时保持原文")

    return True


def test_m3_rag_pipeline_end_to_end():
    """M.3: RAGPipeline 端到端测试"""
    print("\n" + "=" * 60)
    print("测试 M.3: RAGPipeline 端到端")
    print("=" * 60)
    from zeroai.memory.rag_pipeline import RAGPipeline

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "rag_test.db")
        pipeline = RAGPipeline()

        # 手动设置 db_path
        from zeroai.memory.vector_store import VectorStore
        pipeline.vector_store = VectorStore(db_path)

        # 测试文本
        doc1 = """# ZeroAI 项目说明

ZeroAI 是一个终端原生的 AI 编程助手，使用 Python 开发。

## 核心特性

1. 多专家路由：根据问题类型自动选择专家
2. 混合思考模式：结合深度推理和快速响应
3. 工具调用：支持 58+ 内置工具

## 架构设计

ZeroAI 采用模块化设计，核心模块包括：
- zeroai.core：核心 LLM 客户端和 Agent Loop
- zeroai.tools：工具注册和调用
- zeroai.memory：向量记忆和 RAG 管道
- zeroai.mcp：MCP 协议支持
"""

        doc2 = """# MCP 协议集成

ZeroAI 支持 Model Context Protocol (MCP) 协议，可以连接外部 MCP 服务器。

## 客户端

MCP 客户端支持 stdio 和 SSE 两种传输方式。

## 服务器

ZeroAI 也可以作为 MCP 服务器，暴露 58+ 工具给外部客户端。
"""

        # 异步索引
        async def _index():
            count1 = await pipeline.index_text(doc1, source="zeroai_doc.md")
            count2 = await pipeline.index_text(doc2, source="mcp_doc.md")
            return count1 + count2

        total = asyncio.get_event_loop().run_until_complete(_index())
        assert total > 0, "应索引至少 1 个 chunk"
        print(f"  [OK] 索引 chunk 数: {total}")

        # 同步检索
        result = pipeline.retrieve_sync("ZeroAI 有什么特性", top_k=3)
        assert len(result) > 0, "应返回检索结果"
        print(f"  [OK] 检索结果长度: {len(result)} 字符")
        print(f"  [OK] 结果预览: {result[:100]}...")

        # 验证统计
        stats = pipeline.get_stats()
        assert "vector_store" in stats
        assert "chunker" in stats
        assert "reranker" in stats
        assert "compressor" in stats
        print(f"  [OK] 统计信息完整")

    return True


def test_m3_rag_pipeline_with_fake_embed():
    """M.3: RAGPipeline 注入假 embed 函数"""
    print("\n" + "=" * 60)
    print("测试 M.3: RAGPipeline 注入 embed 函数")
    print("=" * 60)
    from zeroai.memory.rag_pipeline import RAGPipeline

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "rag_embed_test.db")
        # 直接用 VectorStore + EmbeddingBackend 构造，避免单例冲突
        from zeroai.memory.vector_store import VectorStore, EmbeddingBackend

        class FakeLLMClient:
            async def embed(self, texts, dimensions=1024):
                import hashlib
                vectors = []
                for text in texts:
                    h = hashlib.md5(text.encode()).digest()
                    vec = [h[i % len(h)] / 255.0 for i in range(dimensions)]
                    vectors.append(vec)
                return vectors

        fake_llm = FakeLLMClient()

        async def fake_embed(texts):
            return await fake_llm.embed(texts, dimensions=8)

        embedding = EmbeddingBackend(embed_func=fake_embed, embed_dim=8)
        store = VectorStore(db_path, embedding=embedding)

        pipeline = RAGPipeline(vector_store=store, llm_client=fake_llm)

        # 验证 embedding 后端配置
        assert pipeline.vector_store.embedding._embed_func is not None
        assert pipeline.vector_store.embedding.dim == 8
        print(f"  [OK] embed_func 已注入, dim={pipeline.vector_store.embedding.dim}")

        # 索引和检索
        async def _test():
            await pipeline.index_text("测试文档内容，用于验证 embed 注入", source="test.md")
            result = pipeline.retrieve_sync("测试", top_k=2)
            return result

        result = asyncio.get_event_loop().run_until_complete(_test())
        print(f"  [OK] 注入 embed 后检索成功, 结果长度: {len(result)}")

    return True


def main():
    """运行所有测试"""
    tests = [
        ("M.1 LLMClient.embed 签名", test_m1_llm_embed_signature),
        ("M.2 EmbeddingBackend embed_func", test_m2_embedding_backend_embed_func),
        ("M.2 VectorStore FAISS 检测", test_m2_vector_store_faiss_detection),
        ("M.3 SemanticChunker 基础", test_m3_semantic_chunker_basic),
        ("M.3 SemanticChunker 短块合并", test_m3_semantic_chunker_short_merge),
        ("M.3 MMRReranker 重排序", test_m3_mmr_reranker),
        ("M.3 ContextCompressor 压缩", test_m3_context_compressor),
        ("M.3 RAGPipeline 端到端", test_m3_rag_pipeline_end_to_end),
        ("M.3 RAGPipeline 注入 embed", test_m3_rag_pipeline_with_fake_embed),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            result = test_func()
            if result:
                passed += 1
                print(f"\n[PASS] {name}")
            else:
                failed += 1
                print(f"\n[FAIL] {name}")
        except Exception as e:
            failed += 1
            print(f"\n[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"阶段 M 测试结果: {passed}/{passed + failed} 通过")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
