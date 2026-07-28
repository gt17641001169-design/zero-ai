"""ZeroAI 向量记忆模块

提供轻量级 RAG 能力，让 AI 能记住项目上下文：
- vector_store.py：基于 numpy + sqlite 的向量存储（零外部依赖）
- project_indexer.py：扫描项目文件并切块索引
- retriever.py：检索接口，供 AgentLoop 调用
- conversation_memory.py：对话历史向量化（阶段 2.2，跨会话记忆）
- file_watcher.py：项目文件后台监视器（阶段 2.5，增量索引）

设计原则：
1. 零外部依赖：不强制要求 faiss/chromadb，用 numpy 实现余弦相似度
2. 可选 embedding：支持 OpenAI/BGE embedding，无 API 时退化为关键词检索
3. 轻量持久化：sqlite 存原文，numpy 存向量，启动快
4. 增量更新：文件变更时只重新索引变更部分
5. 混合检索：向量语义检索 + BM25 关键词检索融合（阶段 2.3）
6. 记忆衰减：时间 + 访问频率衰减，避免噪声淹没（阶段 2.4）
"""
from .vector_store import VectorStore, get_vector_store
from .project_indexer import ProjectIndexer, index_project
from .retriever import Retriever, get_retriever
from .conversation_memory import ConversationMemory, get_conversation_memory
from .file_watcher import FileWatcher, get_file_watcher

__all__ = [
    "VectorStore",
    "get_vector_store",
    "ProjectIndexer",
    "index_project",
    "Retriever",
    "get_retriever",
    "ConversationMemory",
    "get_conversation_memory",
    "FileWatcher",
    "get_file_watcher",
]
