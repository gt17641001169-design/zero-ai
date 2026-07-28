"""项目文件后台监视器 - 文件变更时增量索引

阶段 2.5：避免每次手动 /索引，文件保存时自动增量更新

策略：
1. 优先用 watchdog 库（如果安装了）—— 实时事件驱动
2. 回退到轮询模式（每 N 秒扫描 mtime）—— 零依赖

特性：
- 后台守护线程，不阻塞主循环
- 只重新索引变更的文件（按 mtime 判断）
- 支持防抖（debounce）：批量保存时只索引一次
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .project_indexer import ProjectIndexer
from .vector_store import VectorStore, get_vector_store


class FileWatcher:
    """项目文件后台监视器

    用法：
        watcher = FileWatcher(root_dir="d:/C/C")
        watcher.start()  # 启动后台监视
        # 文件变更时自动增量索引
        watcher.stop()   # 停止

    或一次性使用：
        watcher = FileWatcher(root_dir="d:/C/C")
        changed = watcher.scan_changes()  # 返回变更文件列表
    """

    def __init__(
        self,
        root_dir: str,
        indexer: Optional[ProjectIndexer] = None,
        store: Optional[VectorStore] = None,
        interval: float = 60.0,
        debounce_seconds: float = 5.0,
    ):
        """初始化

        Args:
            root_dir: 监视的项目根目录
            indexer: 项目索引器，为 None 时自动创建
            store: VectorStore，为 None 时用默认单例
            interval: 轮询间隔（秒），仅轮询模式用
            debounce_seconds: 防抖时间（秒），批量变更时等待此时间后再索引
        """
        self.root_dir = os.path.abspath(root_dir)
        self.store = store or get_vector_store()
        self.indexer = indexer or ProjectIndexer(store=self.store)
        self.interval = interval
        self.debounce_seconds = debounce_seconds

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._file_mtimes: Dict[str, float] = {}
        self._pending_changes: Dict[str, float] = {}  # path -> mtime
        self._last_index_time: float = 0.0
        self._lock = threading.Lock()

        # 尝试加载 watchdog
        try:
            from watchdog.observers import Observer  # type: ignore
            from watchdog.events import FileSystemEventHandler  # type: ignore
            self._watchdog_available = True
        except ImportError:
            self._watchdog_available = False

    def scan_changes(self) -> List[str]:
        """扫描变更的文件（一次性，不启动后台线程）

        Returns:
            变更的文件路径列表
        """
        files = self.indexer.scan_files(self.root_dir)
        changed = []
        for fpath in files:
            try:
                mtime = os.path.getmtime(fpath)
                if self._file_mtimes.get(fpath) != mtime:
                    changed.append(fpath)
                    self._file_mtimes[fpath] = mtime
            except OSError:
                continue
        return changed

    def start(self) -> bool:
        """启动后台监视

        Returns:
            True 表示启动成功
        """
        if self._running:
            return True

        # 首次扫描，记录当前所有文件的 mtime
        files = self.indexer.scan_files(self.root_dir)
        for fpath in files:
            try:
                self._file_mtimes[fpath] = os.path.getmtime(fpath)
            except OSError:
                pass

        self._running = True

        # 优先用 watchdog
        if self._watchdog_available:
            try:
                self._start_watchdog()
                return True
            except Exception:
                pass  # watchdog 启动失败，回退到轮询

        # 回退到轮询
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """停止后台监视"""
        self._running = False
        if hasattr(self, "_observer") and self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
            self._thread = None

    def _start_watchdog(self) -> None:
        """用 watchdog 启动实时监视"""
        from watchdog.observers import Observer  # type: ignore
        from watchdog.events import FileSystemEventHandler  # type: ignore

        watcher_self = self

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                path = event.src_path
                watcher_self._on_file_changed(path)

            def on_created(self, event):
                if event.is_directory:
                    return
                path = event.src_path
                watcher_self._on_file_changed(path)

        self._observer = Observer()
        self._observer.schedule(_Handler(), self.root_dir, recursive=True)
        self._observer.start()

    def _on_file_changed(self, path: str) -> None:
        """文件变更回调（watchdog 模式）"""
        # 检查是否为支持的文件
        ext = os.path.splitext(path)[1].lower()
        from .project_indexer import SUPPORTED_EXTENSIONS, _should_skip
        if ext not in SUPPORTED_EXTENSIONS:
            return
        if _should_skip(path):
            return

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return

        with self._lock:
            self._pending_changes[path] = mtime

        # 防抖：延迟索引
        threading.Timer(self.debounce_seconds, self._flush_pending).start()

    def _flush_pending(self) -> None:
        """刷新待索引的变更文件"""
        with self._lock:
            if not self._pending_changes:
                return
            pending = dict(self._pending_changes)
            self._pending_changes.clear()

        # 在独立事件循环中增量索引
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            for fpath in pending:
                try:
                    loop.run_until_complete(
                        self.indexer.index_file(fpath, root_dir=self.root_dir)
                    )
                except Exception:
                    pass
            loop.close()
        except Exception:
            pass

    def _poll_loop(self) -> None:
        """轮询循环（轮询模式）"""
        while self._running:
            try:
                changed = self.scan_changes()
                if changed:
                    # 防抖：等待 debounce_seconds 后再索引
                    time.sleep(self.debounce_seconds)
                    # 再次扫描（可能在防抖期间又有变更）
                    changed = self.scan_changes()
                    if changed and self._running:
                        self._index_files(changed)
            except Exception:
                pass

            # 等待下一轮
            sleep_count = 0
            sleep_interval = 1.0
            target_sleep = int(self.interval / sleep_interval)
            while sleep_count < target_sleep and self._running:
                time.sleep(sleep_interval)
                sleep_count += 1

    def _index_files(self, files: List[str]) -> None:
        """增量索引文件列表"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            for fpath in files:
                try:
                    loop.run_until_complete(
                        self.indexer.index_file(fpath, root_dir=self.root_dir)
                    )
                except Exception:
                    pass
            loop.close()
            self._last_index_time = time.time()
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        """获取监视器状态"""
        return {
            "running": self._running,
            "mode": "watchdog" if self._watchdog_available else "polling",
            "watched_files": len(self._file_mtimes),
            "pending_changes": len(self._pending_changes),
            "last_index_time": self._last_index_time,
            "interval": self.interval,
        }


# ============================================================================
# 单例管理
# ============================================================================

_file_watcher_instance: Optional[FileWatcher] = None


def get_file_watcher(
    root_dir: str = ".",
    interval: float = 60.0,
) -> FileWatcher:
    """获取 FileWatcher 单例

    Args:
        root_dir: 监视目录
        interval: 轮询间隔
    """
    global _file_watcher_instance
    if _file_watcher_instance is None:
        _file_watcher_instance = FileWatcher(root_dir=root_dir, interval=interval)
    return _file_watcher_instance


def reset_file_watcher() -> None:
    """重置单例"""
    global _file_watcher_instance
    if _file_watcher_instance:
        _file_watcher_instance.stop()
    _file_watcher_instance = None
