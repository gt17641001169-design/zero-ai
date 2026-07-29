"""真正的 RAG 管道（阶段 M.3）

提供生产级 RAG 能力：
1. 语义分块：按语义边界切分（段落/句子），而非固定长度
2. 混合检索：向量语义 + BM25 关键词 + 元数据过滤
3. 重排序：对 top-k 候选结果用 MMR 多样性重排
4. 上下文压缩：长文档自动摘要后注入 prompt

与 vector_store.py 的关系：
- vector_store.py 提供底层向量存储和检索能力
- rag_pipeline.py 在其之上构建完整 RAG 管道，供 AgentLoop 调用

设计原则：
- 增量追加：不修改 vector_store.py 和 retriever.py
- 可选使用：AgentLoop 可选择用 RAGPipeline 或直接用 Retriever
- 向后兼容：不注入 embedding 函数时回退到 TF-IDF
"""
from __future__ import annotations

import re
import os
import hashlib
from typing import Any, Callable, Dict, List, Optional, Tuple

from .vector_store import VectorStore, EmbeddingBackend, get_vector_store


# ============================================================================
# 语义分块器（阶段 M.3.1）
# ============================================================================

class SemanticChunker:
    """语义分块器：按语义边界切分文档

    分块策略：
    1. 优先按 Markdown 标题切分（## ### 等）
    2. 其次按段落切分（双换行）
    3. 最后按句子切分（。！？.!?）
    4. 超长块按目标大小二次切分
    5. 过短块与下一块合并

    相比固定长度切分的优势：
    - 保持语义完整性（不会在句子中间断开）
    - 代码块保持完整（```...``` 不会被切断）
    - 标题层级作为元数据，增强检索精度
    """

    def __init__(
        self,
        target_chunk_size: int = 512,
        min_chunk_size: int = 100,
        max_chunk_size: int = 1500,
        overlap: int = 50,
    ):
        """初始化

        Args:
            target_chunk_size: 目标块大小（字符数）
            min_chunk_size: 最小块大小（低于此值与下一块合并）
            max_chunk_size: 最大块大小（超过此值强制切分）
            overlap: 块间重叠字符数（保持上下文连贯）
        """
        self.target_size = target_chunk_size
        self.min_size = min_chunk_size
        self.max_size = max_chunk_size
        self.overlap = overlap

    def chunk_text(
        self,
        text: str,
        source: str = "",
    ) -> List[Dict[str, Any]]:
        """将文本按语义边界切分为块

        Args:
            text: 待切分文本
            source: 来源标识（文件路径等）

        Returns:
            [{"content": ..., "source": ..., "section": ..., "chunk_index": ...}]
        """
        if not text.strip():
            return []

        chunks: List[Dict[str, Any]] = []

        # 第1步：按 Markdown 标题切分
        sections = self._split_by_markdown_headers(text)

        # 第2步：每个 section 内按段落和句子进一步切分
        chunk_idx = 0
        for section_title, section_text in sections:
            if not section_text.strip():
                continue

            # 代码块保护：提取代码块，避免在代码块内部切分
            code_blocks, text_with_placeholders = self._extract_code_blocks(section_text)

            # 按段落切分
            paragraphs = self._split_by_paragraphs(text_with_placeholders)

            # 按句子切分并组装成目标大小的块
            current_chunk = ""
            for para in paragraphs:
                # 恢复代码块
                para = self._restore_code_blocks(para, code_blocks)

                if len(current_chunk) + len(para) > self.target_size and current_chunk:
                    # 当前块已达到目标大小，保存并开始新块
                    chunks.append(self._make_chunk(
                        current_chunk, source, section_title, chunk_idx
                    ))
                    chunk_idx += 1
                    # 重叠：保留上一块末尾
                    if self.overlap > 0 and len(current_chunk) > self.overlap:
                        current_chunk = current_chunk[-self.overlap:] + para
                    else:
                        current_chunk = para
                else:
                    current_chunk = current_chunk + "\n\n" + para if current_chunk else para

                # 超长块强制切分
                while len(current_chunk) > self.max_size:
                    cut_point = self._find_cut_point(current_chunk, self.max_size)
                    chunk_content = current_chunk[:cut_point]
                    chunks.append(self._make_chunk(
                        chunk_content, source, section_title, chunk_idx
                    ))
                    chunk_idx += 1
                    overlap_text = current_chunk[max(0, cut_point - self.overlap):]
                    current_chunk = overlap_text + current_chunk[cut_point:]

            # 保存最后一块
            if current_chunk.strip():
                chunks.append(self._make_chunk(
                    current_chunk, source, section_title, chunk_idx
                ))
                chunk_idx += 1

        # 第3步：合并过短的块
        chunks = self._merge_short_chunks(chunks)

        return chunks

    def _split_by_markdown_headers(self, text: str) -> List[Tuple[str, str]]:
        """按 Markdown 标题切分

        Returns:
            [(section_title, section_text), ...]
        """
        # 匹配 Markdown 标题（# ## ### 等）
        header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

        sections: List[Tuple[str, str]] = []
        last_end = 0
        last_title = ""

        for match in header_pattern.finditer(text):
            if match.start() > last_end:
                # 标题前的内容作为无标题 section
                pre_content = text[last_end:match.start()].strip()
                if pre_content:
                    sections.append((last_title, pre_content))
            last_title = match.group(2).strip()
            last_end = match.end()

        # 最后一个 section
        if last_end < len(text):
            final_content = text[last_end:].strip()
            if final_content:
                sections.append((last_title, final_content))
        elif not sections and text.strip():
            # 没有标题，整篇作为一个 section
            sections.append(("", text.strip()))

        return sections if sections else [("", text)]

    def _extract_code_blocks(self, text: str) -> Tuple[Dict[str, str], str]:
        """提取代码块，替换为占位符

        Returns:
            (code_blocks_map, text_with_placeholders)
            code_blocks_map: {placeholder: code_block_content}
        """
        code_blocks: Dict[str, str] = {}
        pattern = re.compile(r'```[\s\S]*?```', re.MULTILINE)

        def _replace(match: re.Match) -> str:
            content = match.group(0)
            placeholder = f"__CODE_BLOCK_{len(code_blocks)}__"
            code_blocks[placeholder] = content
            return placeholder

        text_with_placeholders = pattern.sub(_replace, text)
        return code_blocks, text_with_placeholders

    def _restore_code_blocks(self, text: str, code_blocks: Dict[str, str]) -> str:
        """恢复代码块"""
        for placeholder, content in code_blocks.items():
            text = text.replace(placeholder, content)
        return text

    def _split_by_paragraphs(self, text: str) -> List[str]:
        """按段落切分（双换行）"""
        paragraphs = re.split(r'\n\s*\n', text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _find_cut_point(self, text: str, target_pos: int) -> int:
        """在目标位置附近寻找最佳切分点

        优先在句号、问号、感叹号后切分
        """
        # 在 target_pos 附近寻找句子结束符
        search_range = 100
        start = max(0, target_pos - search_range)
        end = min(len(text), target_pos + search_range)

        # 寻找最后一个句子结束符
        sentence_end_pattern = re.compile(r'[。！？.!?]\s*')
        best_pos = -1
        for match in sentence_end_pattern.finditer(text, start, end):
            if match.end() <= target_pos + search_range:
                best_pos = match.end()

        if best_pos > 0:
            return best_pos

        # 回退到空格或换行
        for i in range(min(target_pos, len(text) - 1), max(0, target_pos - 50), -1):
            if text[i] in ' \n\t':
                return i + 1

        # 最终回退到 target_pos
        return target_pos

    def _make_chunk(
        self,
        content: str,
        source: str,
        section: str,
        chunk_index: int,
    ) -> Dict[str, Any]:
        """构造 chunk 字典"""
        return {
            "content": content.strip(),
            "source": source,
            "section": section,
            "chunk_index": chunk_index,
            "content_hash": hashlib.md5(content.encode("utf-8")).hexdigest(),
            "size": len(content),
        }

    def _merge_short_chunks(
        self,
        chunks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """合并过短的块"""
        if len(chunks) <= 1:
            return chunks

        merged: List[Dict[str, Any]] = []
        i = 0
        while i < len(chunks):
            current = chunks[i]
            # 如果当前块太短，与下一块合并
            while (i + 1 < len(chunks)
                   and len(current["content"]) < self.min_size):
                next_chunk = chunks[i + 1]
                merged_content = current["content"] + "\n\n" + next_chunk["content"]
                current = dict(current)
                current["content"] = merged_content
                current["size"] = len(merged_content)
                current["content_hash"] = hashlib.md5(
                    merged_content.encode("utf-8")
                ).hexdigest()
                i += 1
            merged.append(current)
            i += 1

        return merged

    def chunk_file(self, file_path: str) -> List[Dict[str, Any]]:
        """切分文件内容

        Args:
            file_path: 文件路径

        Returns:
            chunk 列表
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.chunk_text(content, source=file_path)
        except Exception:
            return []


# ============================================================================
# MMR 重排序器（阶段 M.3.3）
# ============================================================================

class MMRReranker:
    """MMR（Maximal Marginal Relevance）重排序器

    在保证相关性的同时，最大化结果多样性，避免返回高度相似的多条结果。

    MMR 公式：
        MMR = λ * Sim(query, doc) - (1-λ) * max(Sim(doc, selected_doc))

    λ=1 时退化为纯相关性排序，λ=0 时纯多样性排序。
    默认 λ=0.7 偏重相关性。
    """

    def __init__(self, lambda_param: float = 0.7):
        """初始化

        Args:
            lambda_param: 相关性 vs 多样性权衡参数（0-1）
        """
        self.lambda_param = lambda_param

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """MMR 重排序

        Args:
            query: 查询文本
            candidates: 候选结果列表（需有 content 和 score 字段）
            top_k: 返回数量

        Returns:
            重排序后的 top_k 结果
        """
        if not candidates:
            return []

        if len(candidates) <= top_k:
            return sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)

        # 简化实现：基于内容相似度的 MMR
        # 计算 query 与每个候选的相关性（用已有 score）
        selected: List[Dict[str, Any]] = []
        remaining = list(candidates)

        while remaining and len(selected) < top_k:
            best_score = -float("inf")
            best_idx = 0

            for i, candidate in enumerate(remaining):
                # 相关性分数
                relevance = candidate.get("score", 0)

                # 多样性惩罚：与已选结果的最大相似度
                diversity_penalty = 0.0
                for sel in selected:
                    sim = self._text_similarity(
                        candidate.get("content", ""),
                        sel.get("content", ""),
                    )
                    diversity_penalty = max(diversity_penalty, sim)

                # MMR 分数
                mmr_score = self.lambda_param * relevance - (1 - self.lambda_param) * diversity_penalty

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = i

            selected.append(remaining.pop(best_idx))

        return selected

    @staticmethod
    def _text_similarity(text1: str, text2: str) -> float:
        """计算两段文本的相似度（Jaccard 简化版）"""
        # 简易分词：英文按词，中文按字
        def _tokenize(text: str) -> set:
            tokens = set()
            for word in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower()):
                tokens.add(word)
            for ch in text:
                if "\u4e00" <= ch <= "\u9fff":
                    tokens.add(ch)
            return tokens

        set1 = _tokenize(text1)
        set2 = _tokenize(text2)

        if not set1 or not set2:
            return 0.0

        intersection = set1 & set2
        union = set1 | set2
        return len(intersection) / len(union) if union else 0.0


# ============================================================================
# 上下文压缩器（阶段 M.3.4）
# ============================================================================

class ContextCompressor:
    """上下文压缩器：长检索结果自动摘要

    当检索结果总长度超过阈值时，对每条结果截断或摘要。
    优先保留开头和结尾（开头通常包含主题，结尾包含结论）。
    """

    def __init__(
        self,
        max_total_length: int = 4000,
        max_per_chunk: int = 800,
    ):
        """初始化

        Args:
            max_total_length: 上下文总长度上限（字符数）
            max_per_chunk: 单个 chunk 最大长度
        """
        self.max_total_length = max_total_length
        self.max_per_chunk = max_per_chunk

    def compress(
        self,
        results: List[Dict[str, Any]],
    ) -> str:
        """压缩检索结果为上下文文本

        Args:
            results: 检索结果列表

        Returns:
            压缩后的上下文文本
        """
        if not results:
            return ""

        total_length = sum(len(r.get("content", "")) for r in results)

        # 如果总长度未超限，直接拼接
        if total_length <= self.max_total_length:
            parts = []
            for i, r in enumerate(results, 1):
                source = r.get("source", "")
                score = r.get("score", 0)
                content = r.get("content", "")
                parts.append(f"[{i}] (来源: {source}, 相关度: {score:.2f})\n{content}")
            return "\n\n---\n\n".join(parts)

        # 需要压缩：计算每个 chunk 的配额
        num_chunks = len(results)
        per_chunk_budget = min(
            self.max_per_chunk,
            self.max_total_length // num_chunks,
        )

        parts = []
        for i, r in enumerate(results, 1):
            content = r.get("content", "")
            source = r.get("source", "")
            score = r.get("score", 0)

            if len(content) > per_chunk_budget:
                # 截断：保留开头一半 + 结尾一半
                head_size = per_chunk_budget // 2
                tail_size = per_chunk_budget - head_size - 20  # 留 20 字符给省略号
                content = (
                    content[:head_size]
                    + "\n...(省略)...\n"
                    + content[-tail_size:]
                )

            parts.append(f"[{i}] (来源: {source}, 相关度: {score:.2f})\n{content}")

        return "\n\n---\n\n".join(parts)


# ============================================================================
# 完整 RAG 管道（阶段 M.3）
# ============================================================================

class RAGPipeline:
    """完整的 RAG 管道

    整合语义分块、混合检索、MMR 重排序、上下文压缩。

    使用方式：
        pipeline = RAGPipeline(llm_client=client)  # 注入 LLMClient 获得最佳效果
        # 索引文档
        await pipeline.index_text(long_text, source="doc1")
        # 检索
        context = await pipeline.retrieve("查询问题", top_k=5)
    """

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        llm_client: Optional[Any] = None,
        chunker: Optional[SemanticChunker] = None,
        reranker: Optional[MMRReranker] = None,
        compressor: Optional[ContextCompressor] = None,
        embedding_dim: int = 1024,
    ):
        """初始化

        Args:
            vector_store: 向量存储，为 None 时用默认单例
            llm_client: LLM 客户端，注入后用其 embed 方法生成高质量向量
                        为 None 时回退到 TF-IDF
            chunker: 语义分块器
            reranker: 重排序器
            compressor: 上下文压缩器
            embedding_dim: 嵌入维度（llm_client 模式生效）
        """
        # 构建 embedding 后端
        embed_func = None
        if llm_client is not None and hasattr(llm_client, "embed"):
            async def _embed_func(texts: List[str]) -> List[List[float]]:
                return await llm_client.embed(texts, dimensions=embedding_dim)
            embed_func = _embed_func
            embedding = EmbeddingBackend(embed_func=embed_func, embed_dim=embedding_dim)
        else:
            embedding = None  # 用 VectorStore 默认的 EmbeddingBackend

        self.vector_store = vector_store or VectorStore(
            db_path=os.path.join(os.path.expanduser("~"), ".zeroai", "rag_memory.db"),
            embedding=embedding,
        )
        self.chunker = chunker or SemanticChunker()
        self.reranker = reranker or MMRReranker()
        self.compressor = compressor or ContextCompressor()
        self.llm_client = llm_client

    async def index_text(
        self,
        text: str,
        source: str = "user_input",
    ) -> int:
        """索引文本

        Args:
            text: 待索引的文本
            source: 来源标识

        Returns:
            索引的 chunk 数量
        """
        chunks = self.chunker.chunk_text(text, source=source)
        if not chunks:
            return 0

        items = []
        for chunk in chunks:
            doc_id = f"{source}#{chunk['chunk_index']}"
            items.append((doc_id, source, chunk["content"]))

        count = await self.vector_store.add_batch(items)
        return count

    async def index_file(self, file_path: str) -> int:
        """索引文件

        Args:
            file_path: 文件路径

        Returns:
            索引的 chunk 数量
        """
        chunks = self.chunker.chunk_file(file_path)
        if not chunks:
            return 0

        items = []
        for chunk in chunks:
            doc_id = f"{file_path}#{chunk['chunk_index']}"
            items.append((doc_id, file_path, chunk["content"]))

        count = await self.vector_store.add_batch(items)
        return count

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        use_mmr: bool = True,
        use_compression: bool = True,
    ) -> str:
        """检索并返回压缩后的上下文文本

        Args:
            query: 查询文本
            top_k: 返回数量
            use_mmr: 是否使用 MMR 重排序
            use_compression: 是否压缩上下文

        Returns:
            上下文文本（供注入 prompt）
        """
        # 混合检索（向量 + BM25）
        candidates = self.vector_store.hybrid_search(query, top_k=top_k * 2)

        if not candidates:
            return ""

        # MMR 重排序
        if use_mmr:
            candidates = self.reranker.rerank(query, candidates, top_k=top_k)
        else:
            candidates = candidates[:top_k]

        # 上下文压缩
        if use_compression:
            return self.compressor.compress(candidates)
        else:
            parts = []
            for i, r in enumerate(candidates, 1):
                parts.append(f"[{i}] {r.get('content', '')}")
            return "\n\n---\n\n".join(parts)

    def retrieve_sync(
        self,
        query: str,
        top_k: int = 5,
        use_mmr: bool = True,
        use_compression: bool = True,
    ) -> str:
        """同步检索（回退到 TF-IDF）

        与 retrieve() 的区别：
        - retrieve(): 用 API embedding 生成查询向量（异步，精度高）
        - retrieve_sync(): 用 TF-IDF 生成查询向量（同步，零依赖）
        """
        # 同步检索用 search() 而非 search_async()
        candidates = self.vector_store.hybrid_search(query, top_k=top_k * 2)

        if not candidates:
            return ""

        if use_mmr:
            candidates = self.reranker.rerank(query, candidates, top_k=top_k)
        else:
            candidates = candidates[:top_k]

        if use_compression:
            return self.compressor.compress(candidates)
        else:
            parts = []
            for i, r in enumerate(candidates, 1):
                parts.append(f"[{i}] {r.get('content', '')}")
            return "\n\n---\n\n".join(parts)

    def get_stats(self) -> Dict[str, Any]:
        """获取 RAG 管道统计信息"""
        return {
            "vector_store": self.vector_store.get_stats_enhanced(),
            "chunker": {
                "target_size": self.chunker.target_size,
                "min_size": self.chunker.min_size,
                "max_size": self.chunker.max_size,
                "overlap": self.chunker.overlap,
            },
            "reranker": {
                "lambda": self.reranker.lambda_param,
            },
            "compressor": {
                "max_total_length": self.compressor.max_total_length,
                "max_per_chunk": self.compressor.max_per_chunk,
            },
            "embedding": {
                "dim": self.vector_store.embedding.dim,
                "api_available": self.vector_store.embedding._api_available,
                "has_embed_func": self.vector_store.embedding._embed_func is not None,
            },
        }


# ============================================================================
# 单例管理
# ============================================================================

_rag_pipeline_instance: Optional[RAGPipeline] = None


def get_rag_pipeline(
    llm_client: Optional[Any] = None,
    force_new: bool = False,
) -> RAGPipeline:
    """获取 RAG 管道单例

    Args:
        llm_client: LLM 客户端，注入后用其 embed 方法
                    首次调用时注入有效，后续调用忽略（除非 force_new=True）
        force_new: 是否强制创建新实例

    Returns:
        RAGPipeline 实例
    """
    global _rag_pipeline_instance
    if _rag_pipeline_instance is None or force_new:
        _rag_pipeline_instance = RAGPipeline(llm_client=llm_client)
    return _rag_pipeline_instance


def reset_rag_pipeline() -> None:
    """重置单例"""
    global _rag_pipeline_instance
    _rag_pipeline_instance = None


__all__ = [
    "SemanticChunker",
    "MMRReranker",
    "ContextCompressor",
    "RAGPipeline",
    "get_rag_pipeline",
    "reset_rag_pipeline",
]
