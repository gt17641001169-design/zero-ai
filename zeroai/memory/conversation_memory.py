"""对话历史向量化 - 让 AI 跨会话记得用户偏好和历史决策

阶段 2.2：每轮对话结束后入库，新对话开始时检索相关历史

功能：
1. add_turn()：记录一轮对话（user + assistant）到向量库
2. recall()：检索相关历史对话
3. recall_hybrid()：混合检索（向量 + BM25）
4. extract_preferences()：从对话中提取用户偏好并持久化
5. get_user_profile()：读取已提取的用户偏好

设计原则：
- 对话作为 source="conversation" 的 chunk 入库，与项目代码索引隔离
- 用户偏好单独存储在 sqlite meta 表，键为 "user_preferences"
- 检索时通过 source 过滤，只返回对话记忆
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from .vector_store import VectorStore, get_vector_store


class ConversationMemory:
    """对话记忆管理器

    让 Agent 跨会话记住用户偏好和历史决策。

    用法：
        memory = ConversationMemory()
        await memory.add_turn("帮我写个函数", "def hello(): ...")
        # 新会话开始时
        history = memory.recall("写函数")
        # → 返回相关历史对话
    """

    def __init__(self, store: Optional[VectorStore] = None):
        """初始化

        Args:
            store: VectorStore 实例，为 None 时用默认单例
        """
        self.store = store or get_vector_store()

    async def add_turn(
        self,
        user_input: str,
        assistant_response: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """记录一轮对话到向量库

        Args:
            user_input: 用户输入
            assistant_response: 助手回答
            metadata: 额外元数据（如使用的工具、专家等）

        Returns:
            True 表示新增成功
        """
        if not user_input.strip():
            return False

        # 拼接为完整对话块
        parts = [f"用户: {user_input}"]
        if assistant_response:
            # 限制长度，避免单个 chunk 过大
            resp = assistant_response[:2000]
            parts.append(f"助手: {resp}")
        if metadata:
            # 记录元数据（工具调用、专家等）
            meta_str = json.dumps(metadata, ensure_ascii=False)[:200]
            parts.append(f"元数据: {meta_str}")

        content = "\n".join(parts)
        doc_id = f"conv_{int(time.time() * 1000)}"

        await self.store.add(doc_id, "conversation", content)
        return True

    async def add_turn_batch(
        self,
        turns: List[Dict[str, str]],
    ) -> int:
        """批量记录对话轮次

        Args:
            turns: [{"user": "...", "assistant": "...", "metadata": {...}}, ...]

        Returns:
            新增数量
        """
        items = []
        ts = int(time.time() * 1000)
        for i, turn in enumerate(turns):
            user = turn.get("user", "").strip()
            assistant = turn.get("assistant", "").strip()
            if not user:
                continue
            parts = [f"用户: {user}"]
            if assistant:
                parts.append(f"助手: {assistant[:2000]}")
            metadata = turn.get("metadata")
            if metadata:
                parts.append(f"元数据: {json.dumps(metadata, ensure_ascii=False)[:200]}")
            items.append((
                f"conv_{ts}_{i}",
                "conversation",
                "\n".join(parts),
            ))
        if not items:
            return 0
        return await self.store.add_batch(items)

    def recall(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """检索相关历史对话（向量检索）

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            [{"content": ..., "score": ..., "doc_id": ...}, ...]
        """
        results = self.store.search(query, top_k=top_k * 2)
        # 只保留对话记忆（source=conversation）
        conv_results = [r for r in results if r.get("source") == "conversation"]
        return conv_results[:top_k]

    def recall_hybrid(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """混合检索相关历史对话（向量 + BM25）

        比 recall() 更精准，特别适合关键词明确的查询。
        """
        results = self.store.hybrid_search(query, top_k=top_k * 2)
        conv_results = [r for r in results if r.get("source") == "conversation"]
        return conv_results[:top_k]

    async def recall_async(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """异步检索（用 API embedding，精度更高）"""
        results = await self.store.search_async(query, top_k=top_k * 2)
        conv_results = [r for r in results if r.get("source") == "conversation"]
        return conv_results[:top_k]

    # ========================================================================
    # 用户偏好提取与持久化
    # ========================================================================

    def save_preference(self, key: str, value: str) -> None:
        """保存单条用户偏好

        Args:
            key: 偏好键（如 "preferred_language"）
            value: 偏好值（如 "Python"）
        """
        prefs = self._load_preferences()
        prefs[key] = value
        self._save_preferences(prefs)

    def get_preference(self, key: str, default: str = "") -> str:
        """读取单条用户偏好"""
        prefs = self._load_preferences()
        return prefs.get(key, default)

    def get_all_preferences(self) -> Dict[str, str]:
        """读取全部用户偏好"""
        return self._load_preferences()

    def _load_preferences(self) -> Dict[str, str]:
        """从 sqlite meta 表加载用户偏好"""
        try:
            with self.store._lock:
                conn = sqlite3.connect(self.store.db_path)
                cur = conn.execute(
                    "SELECT value FROM meta WHERE key = ?",
                    ("user_preferences",),
                )
                row = cur.fetchone()
                conn.close()
            if row:
                return json.loads(row[0])
        except Exception:
            pass
        return {}

    def _save_preferences(self, prefs: Dict[str, str]) -> None:
        """保存用户偏好到 sqlite meta 表"""
        try:
            with self.store._lock:
                conn = sqlite3.connect(self.store.db_path)
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    ("user_preferences", json.dumps(prefs, ensure_ascii=False)),
                )
                conn.commit()
                conn.close()
        except Exception:
            pass

    def get_stats(self) -> Dict[str, Any]:
        """获取对话记忆统计"""
        try:
            with self.store._lock:
                conn = sqlite3.connect(self.store.db_path)
                cur = conn.execute(
                    "SELECT COUNT(*) FROM chunks WHERE source = 'conversation'"
                )
                count = cur.fetchone()[0]
                conn.close()
            return {"conversation_turns": count}
        except Exception:
            return {"conversation_turns": 0}


# ============================================================================
# 单例管理
# ============================================================================

_conversation_memory_instance: Optional[ConversationMemory] = None


def get_conversation_memory(store: Optional[VectorStore] = None) -> ConversationMemory:
    """获取 ConversationMemory 单例"""
    global _conversation_memory_instance
    if _conversation_memory_instance is None or store is not None:
        _conversation_memory_instance = ConversationMemory(store=store)
    return _conversation_memory_instance


def reset_conversation_memory() -> None:
    """重置单例"""
    global _conversation_memory_instance
    _conversation_memory_instance = None
