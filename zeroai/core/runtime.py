"""运行时状态与可中断异步工具

迁移来源：tui_agent.py 行 272-355, 959-1003

提供：
- RuntimeCache：运行时缓存管理器（临时目录存储，程序退出自动删除）
- runtime_cache：全局缓存实例
- _GLOBAL_STOP / _is_stopped：全局停止标志（Ctrl+C 信号检测）
- _interruptible_await：可中断的 await（周期性检查停止标志）
- _interruptible_sleep：可中断的 sleep

本模块无外部依赖，仅使用标准库 asyncio/tempfile/atexit/shutil/pathlib。
"""
import asyncio
import atexit
import shutil
import tempfile
from pathlib import Path


# ====== 运行时缓存（停止运行自动删除）======
class RuntimeCache:
    """运行时缓存管理器：所有临时数据存入临时目录，程序退出时自动删除"""

    def __init__(self):
        self._cache_dir = None
        self._initialized = False

    @property
    def cache_dir(self) -> Path:
        """获取缓存目录，不存在则创建"""
        if self._cache_dir is None:
            self._cache_dir = Path(tempfile.mkdtemp(prefix="zeroai_cache_"))
            self._initialized = True
            # 注册退出时清理
            atexit.register(self.cleanup)
        return self._cache_dir

    def get_path(self, name: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / name

    def read(self, name: str, default: str = "") -> str:
        """读取缓存文件"""
        p = self.cache_dir / name
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                return default
        return default

    def write(self, name: str, data: str):
        """写入缓存文件"""
        try:
            (self.cache_dir / name).write_text(data, encoding="utf-8")
        except Exception:
            pass

    def read_bytes(self, name: str) -> bytes:
        """读取缓存二进制文件"""
        p = self.cache_dir / name
        if p.exists():
            try:
                return p.read_bytes()
            except Exception:
                return b""
        return b""

    def write_bytes(self, name: str, data: bytes):
        """写入缓存二进制文件"""
        try:
            (self.cache_dir / name).write_bytes(data)
        except Exception:
            pass

    def exists(self, name: str) -> bool:
        """检查缓存文件是否存在"""
        return (self.cache_dir / name).exists()

    def cleanup(self):
        """清理缓存目录（程序退出时自动调用）"""
        if self._cache_dir is not None and self._cache_dir.exists():
            try:
                shutil.rmtree(self._cache_dir, ignore_errors=True)
            except Exception:
                pass

    def size(self) -> int:
        """获取缓存总大小（字节）"""
        if self._cache_dir is None or not self._cache_dir.exists():
            return 0
        total = 0
        for f in self._cache_dir.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except Exception:
                    pass
        return total


# 全局缓存实例
runtime_cache = RuntimeCache()


# ====== 全局停止标志（供独立函数检查 Ctrl+C 状态，避免无法中断的阻塞）======
_GLOBAL_STOP = False


def _is_stopped() -> bool:
    """检查是否收到停止信号（Ctrl+C）"""
    return _GLOBAL_STOP


def _set_stop_flag(value: bool = True):
    """设置全局停止标志（供 TUI 层在 Ctrl+C 时调用）

    注意：tui_agent.py 中直接对 _GLOBAL_STOP 赋值，本函数提供等价能力。
    """
    global _GLOBAL_STOP
    _GLOBAL_STOP = value


async def _interruptible_await(coro, check_interval: float = 0.2, timeout: float = None):
    """可中断的 await：周期性检查停止标志，避免 stream=False 的阻塞调用无法中断

    用于包装 stream=False 的 API 调用，使其在 Ctrl+C 时能快速返回 None
    """
    global _GLOBAL_STOP
    if timeout:
        task = asyncio.wait_for(coro, timeout=timeout)
    else:
        task = asyncio.ensure_future(coro)
    while not task.done():
        if _GLOBAL_STOP:
            task.cancel()
            return None
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=check_interval)
            break
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            return None
    return task.result()


async def _interruptible_sleep(seconds: float, check_interval: float = 0.2):
    """可中断的 sleep：替代 asyncio.sleep，Ctrl+C 时立即返回"""
    global _GLOBAL_STOP
    elapsed = 0.0
    while elapsed < seconds:
        if _GLOBAL_STOP:
            return
        step = min(check_interval, seconds - elapsed)
        await asyncio.sleep(step)
        elapsed += step
