"""RAG 检索接口 - 供 AgentLoop 调用

将 VectorStore 的检索能力封装为 AgentLoop 期望的 retriever 接口：
    retriever(query: str) -> List[str]
"""
from __future__ import annotations

from typing import List, Optional, Callable

from .vector_store import VectorStore, get_vector_store


class Retriever:
    """RAG 检索器

    封装 VectorStore，提供简洁的检索接口。
    支持：
    1. 语义检索（向量相似度）
    2. 关键词回退（当向量库为空时）
    3. 结果重排和过滤
    """

    def __init__(
        self,
        store: Optional[VectorStore] = None,
        top_k: int = 3,
        min_score: float = 0.1,
    ):
        """初始化

        Args:
            store: VectorStore 实例，为 None 时用默认单例
            top_k: 返回前 k 个结果
            min_score: 最低相似度阈值
        """
        self.store = store or get_vector_store()
        self.top_k = top_k
        self.min_score = min_score

    def search(self, query: str) -> List[str]:
        """检索相关文档片段

        Args:
            query: 查询文本

        Returns:
            相关文档片段列表（已格式化为字符串）
        """
        if not query or not query.strip():
            return []

        results = self.store.search(query, top_k=self.top_k)

        # 过滤低分结果
        filtered = [r for r in results if r.get("score", 0) >= self.min_score]
        if not filtered:
            return []

        # 格式化为字符串列表
        formatted = []
        for r in filtered:
            source = r.get("source", "?")
            content = r.get("content", "")
            score = r.get("score", 0)
            formatted.append(f"[{source}] (score={score:.2f})\n{content}")
        return formatted

    def __call__(self, query: str) -> List[str]:
        """让 Retriever 实例可直接调用，符合 AgentLoop.retriever 签名"""
        return self.search(query)

    def get_stats(self) -> dict:
        """获取索引统计信息"""
        return self.store.get_stats()


# ============================================================================
# 单例管理
# ============================================================================

_retriever_instance: Optional[Retriever] = None


def get_retriever(top_k: int = 3) -> Retriever:
    """获取 Retriever 单例

    Args:
        top_k: 返回前 k 个结果
    """
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = Retriever(top_k=top_k)
    elif _retriever_instance.top_k != top_k:
        _retriever_instance.top_k = top_k
    return _retriever_instance


def reset_retriever() -> None:
    """重置单例"""
    global _retriever_instance
    _retriever_instance = None
