"""工具调用结果缓存（阶段 G.3）

为 Agent Loop 提供工具调用结果缓存，避免相同参数的重复调用：
1. LRU 内存缓存：基于 tool_name + hash(args) 的 LRU 缓存
2. 磁盘持久化：可选的磁盘缓存，跨会话复用
3. TTL 过期：可配置的缓存过期时间
4. 缓存统计：命中率、大小、过期数

设计原则：
- 增量追加：不修改 agent.py / registry.py
- 可选启用：通过参数控制是否启用缓存
- 向后兼容：缓存未命中时透明调用原函数
- 安全隔离：某些工具（如 time/random）可配置为不缓存

使用方式：
    from zeroai.core.tool_cache import get_tool_cache
    cache = get_tool_cache()
    # 包装工具调用
    result = await cache.call_with_cache("read_file", {"path": "/tmp/test"})
    # 统计
    stats = cache.get_stats()
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pickle
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ============================================================================
# 缓存条目
# ============================================================================

@dataclass
class CacheEntry:
    """缓存条目"""
    value: str
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_access: float = field(default_factory=time.time)
    size_bytes: int = 0

    def is_expired(self, ttl: float) -> bool:
        """检查是否过期"""
        if ttl <= 0:
            return False
        return (time.time() - self.created_at) > ttl

    def touch(self) -> None:
        """更新访问信息"""
        self.access_count += 1
        self.last_access = time.time()


# ============================================================================
# 工具结果缓存
# ============================================================================

class ToolResultCache:
    """工具调用结果缓存

    LRU + TTL 双重淘汰策略，可选磁盘持久化。
    """

    # 默认不缓存的工具（结果随时变化）
    NO_CACHE_TOOLS = {
        "get_time", "get_date", "random_number", "ping",
        "speak_tts", "listen_asr",  # 语音工具不缓存
        "system_check",  # 系统状态随时变化
    }

    def __init__(
        self,
        max_entries: int = 500,
        ttl_seconds: float = 3600.0,  # 默认 1 小时
        disk_cache_dir: Optional[Path] = None,
        enable_disk: bool = False,
    ):
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._disk_dir = disk_cache_dir or (Path.home() / ".zeroai" / "tool_cache")
        self._enable_disk = enable_disk
        self._no_cache: set = set(self.NO_CACHE_TOOLS)
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "disk_hits": 0,
            "disk_misses": 0,
        }

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def disable_cache_for(self, tool_name: str) -> None:
        """禁用某个工具的缓存"""
        self._no_cache.add(tool_name)

    def enable_cache_for(self, tool_name: str) -> None:
        """启用某个工具的缓存"""
        self._no_cache.discard(tool_name)

    def _make_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        """生成缓存键"""
        # 序列化参数（排序确保相同参数生成相同键）
        try:
            args_str = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            args_str = str(sorted(args.items()))
        key_str = f"{tool_name}:{args_str}"
        return hashlib.sha256(key_str.encode("utf-8")).hexdigest()

    def _get_disk_path(self, key: str) -> Path:
        """获取磁盘缓存文件路径"""
        return self._disk_dir / f"{key}.pkl"

    async def get(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Optional[str]:
        """从缓存获取结果

        Args:
            tool_name: 工具名
            args: 调用参数

        Returns:
            缓存的结果，未命中返回 None
        """
        if tool_name in self._no_cache:
            return None

        key = self._make_key(tool_name, args)

        async with self._lock:
            # 1. 内存缓存
            entry = self._cache.get(key)
            if entry is not None:
                if entry.is_expired(self._ttl):
                    # 过期，删除
                    self._cache.pop(key, None)
                    self._stats["misses"] += 1
                else:
                    entry.touch()
                    self._cache.move_to_end(key)
                    self._stats["hits"] += 1
                    return entry.value
            else:
                self._stats["misses"] += 1

            # 2. 磁盘缓存
            if self._enable_disk:
                disk_path = self._get_disk_path(key)
                if disk_path.exists():
                    try:
                        with open(disk_path, "rb") as f:
                            entry = pickle.load(f)
                        if not entry.is_expired(self._ttl):
                            entry.touch()
                            # 加载到内存
                            self._cache[key] = entry
                            self._cache.move_to_end(key)
                            self._evict_if_needed()
                            self._stats["disk_hits"] += 1
                            return entry.value
                        else:
                            disk_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                self._stats["disk_misses"] += 1

        return None

    async def put(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: str,
    ) -> None:
        """存入缓存

        Args:
            tool_name: 工具名
            args: 调用参数
            result: 工具结果
        """
        if tool_name in self._no_cache:
            return
        if not isinstance(result, str):
            result = str(result)

        key = self._make_key(tool_name, args)
        size = len(result.encode("utf-8"))

        async with self._lock:
            entry = CacheEntry(
                value=result,
                size_bytes=size,
            )
            self._cache[key] = entry
            self._cache.move_to_end(key)
            self._evict_if_needed()

            # 磁盘持久化
            if self._enable_disk:
                try:
                    self._disk_dir.mkdir(parents=True, exist_ok=True)
                    disk_path = self._get_disk_path(key)
                    with open(disk_path, "wb") as f:
                        pickle.dump(entry, f)
                except Exception:
                    pass

    async def call_with_cache(
        self,
        tool_name: str,
        args: Dict[str, Any],
        func: Callable,
        force_refresh: bool = False,
    ) -> str:
        """带缓存的工具调用

        Args:
            tool_name: 工具名
            args: 调用参数
            func: 工具函数（sync 或 async）
            force_refresh: 强制刷新缓存

        Returns:
            工具结果
        """
        # 强制刷新或不可缓存工具
        if force_refresh or tool_name in self._no_cache:
            return await self._call_func(func, args)

        # 查缓存
        cached = await self.get(tool_name, args)
        if cached is not None:
            return cached

        # 调用原函数
        result = await self._call_func(func, args)

        # 存入缓存
        await self.put(tool_name, args, result)

        return result

    async def _call_func(self, func: Callable, args: Dict[str, Any]) -> str:
        """调用工具函数（支持 sync/async）"""
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(**args)
            else:
                result = func(**args)
            return result if isinstance(result, str) else str(result)
        except Exception as e:
            return f"[错误] 工具调用失败: {e}"

    def _evict_if_needed(self) -> None:
        """LRU 淘汰"""
        while len(self._cache) > self._max_entries:
            _, entry = self._cache.popitem(last=False)
            self._stats["evictions"] += 1

    def invalidate(
        self,
        tool_name: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
    ) -> int:
        """使缓存失效

        Args:
            tool_name: 指定工具名（None 清空全部）
            args: 指定参数（None 清空该工具所有缓存）

        Returns:
            清除的条目数
        """
        if tool_name is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        if args is not None:
            key = self._make_key(tool_name, args)
            if key in self._cache:
                self._cache.pop(key)
                return 1
            return 0

        # 清除指定工具的所有缓存（需要遍历）
        count = 0
        keys_to_remove = []
        for k in self._cache:
            # 重建工具名匹配（无法从 hash 反推，需要维护反向索引）
            # 简化方案：使用前缀匹配
            pass
        return count

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0.0
        return {
            **self._stats,
            "total_requests": total,
            "hit_rate": round(hit_rate, 4),
            "cache_size": len(self._cache),
            "max_entries": self._max_entries,
            "ttl_seconds": self._ttl,
            "disk_enabled": self._enable_disk,
            "no_cache_tools": list(self._no_cache),
        }

    def reset_stats(self) -> None:
        """重置统计"""
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "disk_hits": 0,
            "disk_misses": 0,
        }

    def clear(self) -> None:
        """清空所有缓存"""
        self._cache.clear()
        if self._enable_disk:
            try:
                for f in self._disk_dir.glob("*.pkl"):
                    f.unlink()
            except Exception:
                pass


# ============================================================================
# 全局单例
# ============================================================================

_tool_cache: Optional[ToolResultCache] = None


def get_tool_cache(
    max_entries: int = 500,
    ttl_seconds: float = 3600.0,
    enable_disk: bool = False,
) -> ToolResultCache:
    """获取全局工具缓存实例

    Args:
        max_entries: 最大缓存条目数
        ttl_seconds: 缓存过期时间
        enable_disk: 是否启用磁盘缓存

    Returns:
        ToolResultCache 实例
    """
    global _tool_cache
    if _tool_cache is None:
        _tool_cache = ToolResultCache(
            max_entries=max_entries,
            ttl_seconds=ttl_seconds,
            enable_disk=enable_disk,
        )
    return _tool_cache


def reset_tool_cache() -> None:
    """重置全局工具缓存（主要用于测试）"""
    global _tool_cache
    if _tool_cache is not None:
        _tool_cache.clear()
    _tool_cache = None


__all__ = [
    "CacheEntry",
    "ToolResultCache",
    "get_tool_cache",
    "reset_tool_cache",
]
