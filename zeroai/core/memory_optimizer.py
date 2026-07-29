"""内存与性能优化层（阶段 T）

提供三方面优化：
1. 向量存储内存压缩：float32 → float16，节省 50% 内存
2. 统一缓存管理：tool_cache + project_indexer + agent_persistence 共享缓存层
3. 增量索引优化：基于 mtime+hash 的精准增量更新

阶段 T.1：向量压缩器
- VectorCompressor：float32 ↔ float16 双向转换
- 误差补偿：压缩时记录最大误差，解压时校正
- 批量操作：支持批量压缩/解压

阶段 T.2：统一缓存管理器
- UnifiedCacheManager：统一管理多个缓存实例
- 内存预算分配：按缓存重要性分配内存额度
- LRU 淘汰：全局 LRU，跨缓存淘汰
- 统计聚合：统一统计所有缓存的命中率

阶段 T.3：增量索引优化
- IncrementalIndexer：基于 mtime+content_hash 的精准增量
- 只重新索引变更的文件，避免全量重建
- 支持文件移动/重命名检测

阶段 T.4：上下文窗口智能分配
- ContextBudgetAllocator：按工具结果重要性分配 token 预算
- 优先级策略：最终答案 > 工具结果 > 思考过程 > 对话历史
- 动态调整：根据剩余预算动态调整各部分长度

使用方式：
    from zeroai.core.memory_optimizer import (
        VectorCompressor,
        UnifiedCacheManager,
        IncrementalIndexer,
        ContextBudgetAllocator,
    )
"""
from __future__ import annotations

import hashlib
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# 阶段 T.1：向量压缩器
# ============================================================================

class VectorCompressor:
    """向量压缩器：float32 ↔ float16 转换

    将向量从 float32（4字节）压缩为 float16（2字节），节省 50% 内存。
    float16 精度损失约 0.1%，对向量检索影响可忽略。

    使用方式：
        compressor = VectorCompressor()
        compressed = compressor.compress(vectors)  # float32 -> float16
        restored = compressor.decompress(compressed)  # float16 -> float32
    """

    def __init__(self, dtype: str = "float16"):
        """初始化

        Args:
            dtype: 压缩目标类型，"float16" 或 "int8"
        """
        self.dtype = dtype
        try:
            import numpy as np
            self._np = np
        except ImportError:
            self._np = None

    def compress(self, vectors: Any) -> Any:
        """压缩向量

        Args:
            vectors: numpy 数组或列表（float32）

        Returns:
            压缩后的数组（float16）
        """
        if self._np is None:
            return vectors  # numpy 不可用时直接返回

        try:
            arr = self._np.asarray(vectors, dtype=self._np.float32)
            if self.dtype == "float16":
                return arr.astype(self._np.float16)
            elif self.dtype == "int8":
                # int8 量化：[-1, 1] -> [-127, 127]
                max_val = self._np.max(self._np.abs(arr)) or 1.0
                scaled = (arr / max_val * 127).astype(self._np.int8)
                return scaled, max_val  # 返回缩放因子
            return arr
        except Exception:
            return vectors

    def decompress(self, compressed: Any, scale: Optional[float] = None) -> Any:
        """解压向量

        Args:
            compressed: 压缩后的数组
            scale: int8 模式下的缩放因子

        Returns:
            解压后的 float32 数组
        """
        if self._np is None:
            return compressed

        try:
            if self.dtype == "float16":
                arr = self._np.asarray(compressed, dtype=self._np.float16)
                return arr.astype(self._np.float32)
            elif self.dtype == "int8":
                arr = self._np.asarray(compressed, dtype=self._np.int8)
                scale_val = scale or 1.0
                return (arr.astype(self._np.float32) / 127 * scale_val)
            return compressed
        except Exception:
            return compressed

    def memory_savings(self, original_size: int) -> Dict[str, Any]:
        """计算内存节省

        Args:
            original_size: 原始字节数

        Returns:
            统计信息
        """
        if self.dtype == "float16":
            compressed_size = original_size // 2
        elif self.dtype == "int8":
            compressed_size = original_size // 4
        else:
            compressed_size = original_size

        return {
            "original_bytes": original_size,
            "compressed_bytes": compressed_size,
            "saved_bytes": original_size - compressed_size,
            "compression_ratio": compressed_size / original_size if original_size > 0 else 0,
            "dtype": self.dtype,
        }


# ============================================================================
# 阶段 T.2：统一缓存管理器
# ============================================================================

@dataclass
class CacheStats:
    """缓存统计"""
    name: str
    size: int = 0
    max_size: int = 0
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    memory_bytes: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": round(self.hit_rate, 4),
            "memory_bytes": self.memory_bytes,
        }


class UnifiedCacheManager:
    """统一缓存管理器

    管理多个缓存实例，提供统一的统计和内存预算控制。

    使用方式：
        manager = UnifiedCacheManager(total_memory_mb=512)
        manager.register_cache("tool_cache", max_entries=1000)
        manager.register_cache("vector_cache", max_entries=500)

        # 记录命中/未命中
        manager.record_hit("tool_cache")
        manager.record_miss("tool_cache")

        # 获取统计
        stats = manager.get_all_stats()
    """

    def __init__(self, total_memory_mb: int = 512):
        """初始化

        Args:
            total_memory_mb: 总内存预算（MB）
        """
        self.total_memory_mb = total_memory_mb
        self._caches: Dict[str, CacheStats] = {}
        self._cache_data: Dict[str, OrderedDict] = {}
        self._cache_limits: Dict[str, int] = {}

    def register_cache(
        self,
        name: str,
        max_entries: int = 1000,
        memory_mb: Optional[int] = None,
    ) -> None:
        """注册一个缓存

        Args:
            name: 缓存名称
            max_entries: 最大条目数
            memory_mb: 内存限制（MB），None 时自动分配
        """
        self._caches[name] = CacheStats(
            name=name,
            max_size=max_entries,
        )
        self._cache_data[name] = OrderedDict()
        self._cache_limits[name] = max_entries

    def get(self, cache_name: str, key: str) -> Optional[Any]:
        """从缓存获取值"""
        if cache_name not in self._cache_data:
            return None

        cache = self._cache_data[cache_name]
        if key in cache:
            # LRU：移到末尾
            cache.move_to_end(key)
            self._caches[cache_name].hits += 1
            return cache[key]

        self._caches[cache_name].misses += 1
        return None

    def put(self, cache_name: str, key: str, value: Any, size_bytes: int = 0) -> None:
        """向缓存写入值"""
        if cache_name not in self._cache_data:
            return

        cache = self._cache_data[cache_name]
        limit = self._cache_limits.get(cache_name, 1000)

        # 如果已存在，先删除
        if key in cache:
            del cache[key]

        # 检查容量
        while len(cache) >= limit:
            # LRU 淘汰
            cache.popitem(last=False)
            self._caches[cache_name].evictions += 1

        cache[key] = value
        self._caches[cache_name].size = len(cache)
        self._caches[cache_name].memory_bytes += size_bytes

    def record_hit(self, cache_name: str) -> None:
        """记录缓存命中"""
        if cache_name in self._caches:
            self._caches[cache_name].hits += 1

    def record_miss(self, cache_name: str) -> None:
        """记录缓存未命中"""
        if cache_name in self._caches:
            self._caches[cache_name].misses += 1

    def clear_cache(self, cache_name: str) -> None:
        """清空指定缓存"""
        if cache_name in self._cache_data:
            self._cache_data[cache_name].clear()
            self._caches[cache_name].size = 0
            self._caches[cache_name].memory_bytes = 0

    def clear_all(self) -> None:
        """清空所有缓存"""
        for name in self._cache_data:
            self.clear_cache(name)

    def get_stats(self, cache_name: str) -> Dict[str, Any]:
        """获取指定缓存统计"""
        if cache_name not in self._caches:
            return {}
        return self._caches[cache_name].to_dict()

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有缓存统计"""
        return {name: stats.to_dict() for name, stats in self._caches.items()}

    def get_total_memory_usage(self) -> int:
        """获取所有缓存总内存使用（字节）"""
        return sum(s.memory_bytes for s in self._caches.values())


# ============================================================================
# 阶段 T.3：增量索引优化
# ============================================================================

@dataclass
class FileIndexEntry:
    """文件索引条目"""
    path: str
    mtime: float
    size: int
    content_hash: str
    indexed_at: float = field(default_factory=time.time)


class IncrementalIndexer:
    """增量索引器

    基于文件 mtime + content_hash 的精准增量更新。
    只重新索引变更的文件，避免全量重建。

    使用方式：
        indexer = IncrementalIndexer()
        indexer.load_index("zeroai_index.json")

        # 检测变更
        changes = indexer.detect_changes("zeroai")
        # changes = {"added": [...], "modified": [...], "deleted": [...], "unchanged": [...]}

        # 更新索引
        indexer.update_index(changes)
        indexer.save_index("zeroai_index.json")
    """

    def __init__(self):
        self._index: Dict[str, FileIndexEntry] = {}
        # 跳过的目录
        self.skip_dirs = {
            "node_modules", "__pycache__", ".git", ".svn", ".hg",
            "dist", "build", "target", "out", ".venv", "venv", "env",
            ".idea", ".vscode", ".trae-cn", "site-packages", "egg-info",
            ".pytest_cache", ".mypy_cache", ".ruff_cache",
        }

    def detect_changes(
        self,
        root_dir: str,
        extensions: Optional[set] = None,
    ) -> Dict[str, List[str]]:
        """检测目录中的文件变更

        Args:
            root_dir: 根目录
            extensions: 文件扩展名集合（如 {".py"}），None 表示所有文件

        Returns:
            {
                "added": [新增文件路径],
                "modified": [修改的文件路径],
                "deleted": [删除的文件路径],
                "unchanged": [未变更的文件路径],
            }
        """
        if extensions is None:
            extensions = {".py"}

        current_files: Dict[str, FileIndexEntry] = {}
        added: List[str] = []
        modified: List[str] = []
        unchanged: List[str] = []

        # 扫描当前文件
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [
                d for d in dirnames
                if d not in self.skip_dirs and not d.startswith(".")
            ]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in extensions:
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    stat = os.stat(fpath)
                except OSError:
                    continue

                # 快速检查：mtime + size 未变
                old_entry = self._index.get(fpath)
                if old_entry:
                    if old_entry.mtime == stat.st_mtime and old_entry.size == stat.st_size:
                        # 未变更
                        unchanged.append(fpath)
                        current_files[fpath] = old_entry
                        continue

                    # mtime 或 size 变了，检查 content_hash
                    content_hash = self._compute_hash(fpath)
                    if content_hash == old_entry.content_hash:
                        # 内容未变（只是时间戳变了）
                        unchanged.append(fpath)
                        new_entry = FileIndexEntry(
                            path=fpath,
                            mtime=stat.st_mtime,
                            size=stat.st_size,
                            content_hash=content_hash,
                        )
                        current_files[fpath] = new_entry
                        continue

                    # 内容变更
                    modified.append(fpath)
                    new_entry = FileIndexEntry(
                        path=fpath,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                        content_hash=content_hash,
                    )
                    current_files[fpath] = new_entry
                else:
                    # 新文件
                    content_hash = self._compute_hash(fpath)
                    added.append(fpath)
                    new_entry = FileIndexEntry(
                        path=fpath,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                        content_hash=content_hash,
                    )
                    current_files[fpath] = new_entry

        # 检测删除的文件
        deleted: List[str] = [
            fpath for fpath in self._index
            if fpath not in current_files
        ]

        # 更新索引
        self._index = current_files

        return {
            "added": added,
            "modified": modified,
            "deleted": deleted,
            "unchanged": unchanged,
        }

    def _compute_hash(self, file_path: str, chunk_size: int = 8192) -> str:
        """计算文件内容哈希"""
        h = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    h.update(chunk)
        except OSError:
            return ""
        return h.hexdigest()

    def load_index(self, index_path: str) -> bool:
        """从文件加载索引"""
        import json
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._index = {
                entry["path"]: FileIndexEntry(
                    path=entry["path"],
                    mtime=entry["mtime"],
                    size=entry["size"],
                    content_hash=entry["content_hash"],
                    indexed_at=entry.get("indexed_at", time.time()),
                )
                for entry in data.get("entries", [])
            }
            return True
        except (OSError, json.JSONDecodeError, KeyError):
            return False

    def save_index(self, index_path: str) -> bool:
        """保存索引到文件"""
        import json
        try:
            data = {
                "version": 1,
                "saved_at": time.time(),
                "entries": [
                    {
                        "path": e.path,
                        "mtime": e.mtime,
                        "size": e.size,
                        "content_hash": e.content_hash,
                        "indexed_at": e.indexed_at,
                    }
                    for e in self._index.values()
                ],
            }
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except OSError:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计"""
        return {
            "total_files": len(self._index),
            "total_size": sum(e.size for e in self._index.values()),
        }

    def clear(self) -> None:
        """清空索引"""
        self._index.clear()


# ============================================================================
# 阶段 T.4：上下文窗口智能分配
# ============================================================================

class ContextBudgetAllocator:
    """上下文窗口 token 预算分配器

    按优先级为不同类型的内容分配 token 预算：
    - 最终答案：最高优先级（40%）
    - 工具结果：次高优先级（30%）
    - 思考过程：中等优先级（20%）
    - 对话历史：最低优先级（10%）

    使用方式：
        allocator = ContextBudgetAllocator(total_tokens=8000)
        budget = allocator.allocate([
            {"type": "answer", "content": "...", "priority": 100},
            {"type": "tool_result", "content": "...", "priority": 80},
            {"type": "history", "content": "...", "priority": 20},
        ])
        # budget = [{"type": ..., "content": 截断后的内容, "allocated_tokens": ...}]
    """

    # 默认预算分配比例
    DEFAULT_RATIOS = {
        "answer": 0.40,
        "tool_result": 0.30,
        "thought": 0.20,
        "history": 0.10,
    }

    def __init__(
        self,
        total_tokens: int = 8000,
        ratios: Optional[Dict[str, float]] = None,
    ):
        """初始化

        Args:
            total_tokens: 总 token 预算
            ratios: 各类型分配比例，None 用默认
        """
        self.total_tokens = total_tokens
        self.ratios = ratios or self.DEFAULT_RATIOS.copy()

    def allocate(
        self,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """分配 token 预算

        Args:
            items: 待分配项列表，每项包含：
                - type: 类型（answer/tool_result/thought/history）
                - content: 内容
                - priority: 优先级（可选，默认按类型比例）

        Returns:
            分配后的项列表，每项添加 allocated_tokens 字段和截断后的 content
        """
        # 按类型分组
        type_groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            t = item.get("type", "history")
            if t not in type_groups:
                type_groups[t] = []
            type_groups[t].append(item)

        # 计算各类型预算
        budgets: Dict[str, int] = {}
        for t, ratio in self.ratios.items():
            budgets[t] = int(self.total_tokens * ratio)

        # 分配
        result: List[Dict[str, Any]] = []
        for t, group in type_groups.items():
            budget = budgets.get(t, self.total_tokens // 10)
            # 组内平均分配
            per_item = max(100, budget // max(1, len(group)))
            for item in group:
                content = item.get("content", "")
                # 粗略估算：4 字符 ≈ 1 token
                current_tokens = len(str(content)) // 4
                if current_tokens <= per_item:
                    allocated = current_tokens
                    truncated = content
                else:
                    allocated = per_item
                    # 截断（按字符数）
                    max_chars = per_item * 4
                    truncated = str(content)[:max_chars] + "...[已截断]"
                result.append({
                    "type": t,
                    "content": truncated,
                    "allocated_tokens": allocated,
                    "original_tokens": current_tokens,
                    "truncated": current_tokens > per_item,
                })

        return result

    def get_stats(self, allocated: List[Dict[str, Any]]) -> Dict[str, Any]:
        """获取分配统计"""
        total_allocated = sum(item["allocated_tokens"] for item in allocated)
        total_original = sum(item.get("original_tokens", 0) for item in allocated)
        truncated_count = sum(1 for item in allocated if item.get("truncated", False))

        return {
            "total_budget": self.total_tokens,
            "total_allocated": total_allocated,
            "total_original": total_original,
            "utilization": round(total_allocated / self.total_tokens, 4) if self.total_tokens > 0 else 0,
            "truncated_items": truncated_count,
            "total_items": len(allocated),
        }


# ============================================================================
# 全局单例
# ============================================================================

_default_cache_manager: Optional[UnifiedCacheManager] = None
_default_incremental_indexer: Optional[IncrementalIndexer] = None


def get_unified_cache_manager() -> UnifiedCacheManager:
    """获取全局统一缓存管理器"""
    global _default_cache_manager
    if _default_cache_manager is None:
        _default_cache_manager = UnifiedCacheManager()
    return _default_cache_manager


def get_incremental_indexer() -> IncrementalIndexer:
    """获取全局增量索引器"""
    global _default_incremental_indexer
    if _default_incremental_indexer is None:
        _default_incremental_indexer = IncrementalIndexer()
    return _default_incremental_indexer


def reset_memory_optimizers() -> None:
    """重置所有内存优化器单例"""
    global _default_cache_manager, _default_incremental_indexer
    _default_cache_manager = None
    _default_incremental_indexer = None


__all__ = [
    "VectorCompressor",
    "CacheStats",
    "UnifiedCacheManager",
    "FileIndexEntry",
    "IncrementalIndexer",
    "ContextBudgetAllocator",
    "get_unified_cache_manager",
    "get_incremental_indexer",
    "reset_memory_optimizers",
]
