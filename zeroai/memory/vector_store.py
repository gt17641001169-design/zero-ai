"""轻量级向量存储 - 基于 numpy + sqlite

特性：
1. 零外部依赖：numpy + sqlite3（Python 内置），不强制 faiss/chromadb
2. Embedding 后端可选：
   - 优先用 OpenAI text-embedding-3-small（如果配置了 API Key）
   - 回退到 BGE-small-zh（如果安装了 sentence-transformers）
   - 最终回退到 TF-IDF 关键词向量（零依赖，纯 numpy 实现）
3. 持久化：sqlite 存原文 + 元数据，numpy 存向量到 .npy
4. 增量更新：支持 add/upsert/delete
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import hashlib
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ============================================================================
# TF-IDF 向量化器（零依赖回退方案）
# ============================================================================

class TfidfVectorizer:
    """简易 TF-IDF 向量化器（纯 numpy 实现）

    用于没有 embedding API 时的回退方案。
    维度固定为 vocab_size，支持中英文混合。
    """

    def __init__(self, max_features: int = 2000, dim: int = 256):
        """初始化

        Args:
            max_features: 最大词汇表大小
            dim: 输出向量维度（通过随机投影降维）
        """
        self.max_features = max_features
        self.dim = dim
        self.vocab: Dict[str, int] = {}
        self.idf: Optional[np.ndarray] = None
        # 随机投影矩阵（固定种子保证可复现）
        rng = np.random.RandomState(42)
        self._projection: Optional[np.ndarray] = None
        self._fitted = False

    def _tokenize(self, text: str) -> List[str]:
        """简易分词：中文按字，英文按词（下划线标识符拆分为子词）

        例如 calculate_sum → ["calculate", "sum", "calculate_sum"]
        这样查询 "calculate sum" 也能匹配 calculate_sum。
        """
        import re
        tokens = []
        # 英文单词（含下划线标识符）
        for word in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower()):
            tokens.append(word)
            # 拆分下划线标识符为子词
            if "_" in word and len(word) > 3:
                parts = word.split("_")
                for part in parts:
                    if part and len(part) > 1:
                        tokens.append(part)
        # 驼峰拆分
        for word in list(tokens):
            camel_parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", word)
            if len(camel_parts) > 1:
                tokens.extend(p.lower() for p in camel_parts if len(p) > 1)
        # 中文单字
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                tokens.append(ch)
        return tokens

    def fit(self, texts: List[str]) -> "TfidfVectorizer":
        """拟合词汇表和 IDF"""
        from collections import Counter

        # 统计词频
        doc_freq: Counter = Counter()
        total_docs = len(texts)
        for text in texts:
            tokens = set(self._tokenize(text))
            for t in tokens:
                doc_freq[t] += 1

        # 取 top max_features
        top = doc_freq.most_common(self.max_features)
        self.vocab = {word: idx for idx, (word, _) in enumerate(top)}

        # 计算 IDF
        idf = np.zeros(len(self.vocab), dtype=np.float32)
        for word, idx in self.vocab.items():
            df = doc_freq[word]
            idf[idx] = np.log((total_docs + 1) / (df + 1)) + 1.0
        self.idf = idf

        # 初始化随机投影矩阵（vocab_size -> dim）
        vocab_size = len(self.vocab)
        if vocab_size > 0:
            rng = np.random.RandomState(42)
            self._projection = rng.randn(vocab_size, self.dim).astype(np.float32) / np.sqrt(self.dim)
        self._fitted = True
        return self

    def transform(self, text: str) -> np.ndarray:
        """将文本转为向量"""
        if not self._fitted or self._projection is None:
            return np.zeros(self.dim, dtype=np.float32)

        tokens = self._tokenize(text)
        tf = np.zeros(len(self.vocab), dtype=np.float32)
        for token in tokens:
            idx = self.vocab.get(token)
            if idx is not None:
                tf[idx] += 1.0

        # TF-IDF
        tfidf = tf * self.idf
        # 随机投影降维
        vec = tfidf @ self._projection
        # L2 归一化
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(np.float32)

    def fit_transform(self, texts: List[str]) -> np.ndarray:
        """拟合并转换"""
        self.fit(texts)
        return np.stack([self.transform(t) for t in texts]) if texts else np.zeros((0, self.dim), dtype=np.float32)


# ============================================================================
# Embedding 后端选择
# ============================================================================

class EmbeddingBackend:
    """Embedding 后端：优先用 API，回退到 TF-IDF"""

    def __init__(self, model_key: str = "glm", api_key: str = "", base_url: str = ""):
        """初始化

        Args:
            model_key: 模型标识（glm / openai）
            api_key: API Key
            base_url: API 地址
        """
        self.model_key = model_key
        self.api_key = api_key
        self.base_url = base_url
        self._tfidf: Optional[TfidfVectorizer] = None
        self._api_available = bool(api_key)

    async def embed_texts(self, texts: List[str]) -> np.ndarray:
        """将文本列表转为向量矩阵

        Returns:
            shape=(len(texts), dim) 的 float32 矩阵
        """
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        # 1. 尝试 API embedding
        if self._api_available:
            try:
                return await self._embed_via_api(texts)
            except Exception:
                self._api_available = False  # 失败后不再重试

        # 2. 回退到 TF-IDF
        return self._embed_via_tfidf(texts)

    @property
    def dim(self) -> int:
        """向量维度"""
        if self._api_available:
            return 1536  # text-embedding-3-small
        return 256  # TF-IDF 降维维度

    async def _embed_via_api(self, texts: List[str]) -> np.ndarray:
        """通过 OpenAI/GLM API 生成 embedding"""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=self.base_url or "https://open.bigmodel.cn/api/paas/v4/",
            api_key=self.api_key,
        )
        # GLM embedding 模型：embedding-3
        model = "embedding-3"
        resp = await client.embeddings.create(model=model, input=texts)
        vectors = [item.embedding for item in resp.data]
        return np.array(vectors, dtype=np.float32)

    def _embed_via_tfidf(self, texts: List[str]) -> np.ndarray:
        """通过 TF-IDF 生成向量"""
        if self._tfidf is None:
            self._tfidf = TfidfVectorizer(dim=256)
            self._tfidf.fit(texts)
        return np.stack([self._tfidf.transform(t) for t in texts]) if texts else np.zeros((0, 256), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """同步嵌入查询文本（用于检索时）"""
        if self._api_available:
            # API 是异步的，同步调用时回退到 TF-IDF
            pass
        if self._tfidf is None:
            # 未拟合，用空向量
            return np.zeros(256, dtype=np.float32)
        vec = self._tfidf.transform(text)
        # 如果查询词全不在 vocab 中，返回零向量（search 会过滤零分结果）
        return vec


# ============================================================================
# 向量存储
# ============================================================================

class VectorStore:
    """向量存储：sqlite 存原文 + numpy 存向量

    数据布局：
    - sqlite 表 chunks(id, doc_id, source, content, hash, created_at)
    - numpy .npy 存向量矩阵（按 chunk id 顺序）
    """

    def __init__(self, db_path: str, embedding: Optional[EmbeddingBackend] = None):
        """初始化

        Args:
            db_path: sqlite 数据库路径
            embedding: Embedding 后端，为 None 时用默认 GLM
        """
        self.db_path = db_path
        self.embedding = embedding or EmbeddingBackend()
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """初始化 sqlite 表结构"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(doc_id, source)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()
            conn.close()

    def _vector_path(self) -> str:
        """向量文件路径"""
        return self.db_path + ".npy"

    def _load_vectors(self) -> np.ndarray:
        """加载向量矩阵"""
        if os.path.exists(self._vector_path()):
            try:
                return np.load(self._vector_path())
            except Exception:
                pass
        return np.zeros((0, self.embedding.dim), dtype=np.float32)

    def _save_vectors(self, vectors: np.ndarray) -> None:
        """保存向量矩阵"""
        np.save(self._vector_path(), vectors)

    async def add(
        self,
        doc_id: str,
        source: str,
        content: str,
    ) -> bool:
        """添加或更新一个文档块

        Returns:
            True 表示新增/更新成功，False 表示内容未变化（hash 相同）
        """
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            # 检查是否已存在且内容相同
            cur = conn.execute(
                "SELECT id, content_hash FROM chunks WHERE doc_id=? AND source=?",
                (doc_id, source),
            )
            row = cur.fetchone()
            if row and row[1] == content_hash:
                conn.close()
                return False  # 内容未变化

            import time
            now = time.time()
            if row:
                # 更新
                conn.execute(
                    "UPDATE chunks SET content=?, content_hash=?, created_at=? WHERE id=?",
                    (content, content_hash, now, row[0]),
                )
                chunk_id = row[0]
            else:
                # 新增
                cur = conn.execute(
                    "INSERT INTO chunks (doc_id, source, content, content_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, source, content, content_hash, now),
                )
                chunk_id = cur.lastrowid
            conn.commit()
            conn.close()

        # 生成向量并更新向量矩阵
        vec = await self.embedding.embed_texts([content])
        if vec.shape[0] == 0:
            return False

        vectors = self._load_vectors()
        # 确保向量维度一致
        if vectors.shape[1] != vec.shape[1]:
            # 维度变了（embedding 后端切换），清空重建
            vectors = np.zeros((0, vec.shape[1]), dtype=np.float32)

        # 扩展或替换
        while vectors.shape[0] < chunk_id:
            # 填充零向量对齐 id
            vectors = np.vstack([vectors, np.zeros((1, vectors.shape[1]), dtype=np.float32)])

        if vectors.shape[0] == chunk_id:
            vectors = np.vstack([vectors, vec])
        else:
            vectors[chunk_id] = vec[0]

        self._save_vectors(vectors)
        return True

    async def add_batch(
        self,
        items: List[Tuple[str, str, str]],  # (doc_id, source, content)
    ) -> int:
        """批量添加文档块

        Returns:
            新增/更新的数量
        """
        if not items:
            return 0
        count = 0
        # 批量生成向量
        contents = [item[2] for item in items]
        vectors = await self.embedding.embed_texts(contents)

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            import time
            now = time.time()
            for (doc_id, source, content), vec in zip(items, vectors):
                content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
                cur = conn.execute(
                    "SELECT id, content_hash FROM chunks WHERE doc_id=? AND source=?",
                    (doc_id, source),
                )
                row = cur.fetchone()
                if row and row[1] == content_hash:
                    continue  # 跳过未变化的

                if row:
                    conn.execute(
                        "UPDATE chunks SET content=?, content_hash=?, created_at=? WHERE id=?",
                        (content, content_hash, now, row[0]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO chunks (doc_id, source, content, content_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                        (doc_id, source, content, content_hash, now),
                    )
                count += 1
            conn.commit()
            conn.close()

        # 重建向量矩阵（简单实现，后续可优化为增量更新）
        if count > 0:
            await self._rebuild_vectors()
        return count

    async def _rebuild_vectors(self) -> None:
        """从 sqlite 重建向量矩阵

        重要：重建时重新 fit TF-IDF，确保 vocab 覆盖所有文档。
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute("SELECT id, content FROM chunks ORDER BY id")
            rows = cur.fetchall()
            conn.close()

        if not rows:
            self._save_vectors(np.zeros((0, self.embedding.dim), dtype=np.float32))
            return

        contents = [r[1] for r in rows]

        # 重新 fit TF-IDF（如果有新文档加入，vocab 需要更新）
        if hasattr(self.embedding, '_tfidf') and self.embedding._tfidf is not None:
            self.embedding._tfidf.fit(contents)

        vectors = await self.embedding.embed_texts(contents)

        # 确保向量矩阵与 chunk id 对齐
        max_id = max(r[0] for r in rows)
        aligned = np.zeros((max_id + 1, vectors.shape[1] if vectors.size else self.embedding.dim), dtype=np.float32)
        for (chunk_id, _), vec in zip(rows, vectors):
            aligned[chunk_id] = vec
        self._save_vectors(aligned)

    def search(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """检索最相关的文档块

        Args:
            query: 查询文本
            top_k: 返回前 k 个结果

        Returns:
            [{"doc_id": ..., "source": ..., "content": ..., "score": ...}, ...]
        """
        # 生成查询向量
        query_vec = self.embedding.embed_query(query)
        if query_vec is None or query_vec.size == 0:
            return []

        vectors = self._load_vectors()
        if vectors.shape[0] == 0:
            return []

        # 余弦相似度（向量已 L2 归一化）
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        vec_norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-8
        normalized = vectors / vec_norms
        scores = normalized @ query_norm

        # 取 top_k
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            for idx in top_indices:
                if scores[idx] <= 0:
                    continue
                cur = conn.execute(
                    "SELECT doc_id, source, content FROM chunks WHERE id=?",
                    (int(idx),),
                )
                row = cur.fetchone()
                if row:
                    results.append({
                        "doc_id": row[0],
                        "source": row[1],
                        "content": row[2],
                        "score": float(scores[idx]),
                    })
            conn.close()

        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute("SELECT COUNT(*), COUNT(DISTINCT source) FROM chunks")
            total, sources = cur.fetchone()
            cur = conn.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source")
            by_source = {row[0]: row[1] for row in cur.fetchall()}
            conn.close()

        vectors = self._load_vectors()
        return {
            "total_chunks": total,
            "total_sources": sources,
            "by_source": by_source,
            "vector_dim": vectors.shape[1] if vectors.size else 0,
            "vector_count": vectors.shape[0],
        }

    def clear(self) -> None:
        """清空所有数据"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM chunks")
            conn.commit()
            conn.close()
        if os.path.exists(self._vector_path()):
            os.remove(self._vector_path())


# ============================================================================
# 单例管理
# ============================================================================

_vector_store_instance: Optional[VectorStore] = None


def get_vector_store(db_path: Optional[str] = None) -> VectorStore:
    """获取 VectorStore 单例

    Args:
        db_path: 数据库路径，为 None 时用默认路径 ~/.zeroai/memory.db
    """
    global _vector_store_instance
    if _vector_store_instance is None or db_path is not None:
        if db_path is None:
            home = os.path.expanduser("~")
            zeroai_dir = os.path.join(home, ".zeroai")
            os.makedirs(zeroai_dir, exist_ok=True)
            db_path = os.path.join(zeroai_dir, "memory.db")
        _vector_store_instance = VectorStore(db_path)
    return _vector_store_instance


def reset_vector_store() -> None:
    """重置单例"""
    global _vector_store_instance
    _vector_store_instance = None
