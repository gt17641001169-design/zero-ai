"""流式思维链输出与中断响应（阶段 P.1）

提供 Agent 思考过程的实时流式输出能力：

1. StreamingThoughtEmitter：流式思维链发射器
   - 实时输出思考过程（不等整段生成）
   - 支持增量追加和回退
   - 可选的缓冲区策略（立即/分块/全量）

2. InterruptionHandler：中断响应处理器
   - 用户可随时打断 Agent 执行
   - 优雅中断：保存当前进度，返回部分结果
   - 中断后可恢复执行

3. ProgressTracker：工具调用进度跟踪器
   - 实时显示工具执行状态
   - 进度条和耗时统计
   - 多工具并行进度

使用方式：
    emitter = StreamingThoughtEmitter(on_chunk=print)
    emitter.start_thought("分析问题")
    emitter.append_chunk("首先...")
    emitter.append_chunk("然后...")
    emitter.end_thought()

    handler = InterruptionHandler()
    handler.check()  # 检查是否被中断
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable, Union


# ============================================================================
# 流式思维链发射器（阶段 P.1.1）
# ============================================================================

@dataclass
class ThoughtChunk:
    """思维链块"""
    text: str
    thought_id: str
    chunk_index: int
    timestamp: float = field(default_factory=time.time)
    is_final: bool = False


class StreamingThoughtEmitter:
    """流式思维链发射器

    实时输出思考过程，支持增量追加。

    缓冲策略：
    - immediate: 立即输出每个 chunk（最低延迟）
    - chunked: 攒满 N 字符后输出（平衡延迟和性能）
    - full: 全部完成后输出（最高性能）

    使用方式：
        emitter = StreamingThoughtEmitter(on_chunk=handler, buffer_mode="immediate")
        emitter.start_thought("分析问题")
        emitter.append_chunk("首先...")
        emitter.end_thought()
    """

    def __init__(
        self,
        on_chunk: Optional[Callable[[ThoughtChunk], None]] = None,
        on_thought_start: Optional[Callable[[str, str], None]] = None,
        on_thought_end: Optional[Callable[[str, str], None]] = None,
        buffer_mode: str = "immediate",
        chunk_size: int = 50,
    ):
        """初始化

        Args:
            on_chunk: chunk 回调函数
            on_thought_start: 思考开始回调 (thought_id, title)
            on_thought_end: 思考结束回调 (thought_id, full_text)
            buffer_mode: 缓冲模式（immediate/chunked/full）
            chunk_size: chunked 模式的块大小
        """
        self._on_chunk = on_chunk
        self._on_thought_start = on_thought_start
        self._on_thought_end = on_thought_end
        self._buffer_mode = buffer_mode
        self._chunk_size = chunk_size

        self._current_thought_id: Optional[str] = None
        self._current_text: str = ""
        self._chunk_index: int = 0
        self._buffer: str = ""
        self._lock = threading.Lock()

    def start_thought(self, title: str = "") -> str:
        """开始一个新的思考

        Args:
            title: 思考标题

        Returns:
            thought_id
        """
        import uuid
        thought_id = str(uuid.uuid4())[:8]

        with self._lock:
            self._current_thought_id = thought_id
            self._current_text = ""
            self._chunk_index = 0
            self._buffer = ""

        if self._on_thought_start:
            try:
                self._on_thought_start(thought_id, title)
            except Exception:
                pass

        return thought_id

    def append_chunk(self, text: str) -> None:
        """追加文本块

        Args:
            text: 文本块
        """
        if not text or not self._current_thought_id:
            return

        with self._lock:
            self._current_text += text
            self._chunk_index += 1

            if self._buffer_mode == "immediate":
                self._emit_chunk(text, is_final=False)
            elif self._buffer_mode == "chunked":
                self._buffer += text
                if len(self._buffer) >= self._chunk_size:
                    self._emit_chunk(self._buffer, is_final=False)
                    self._buffer = ""
            # full 模式：不输出，等 end_thought

    def end_thought(self) -> str:
        """结束当前思考

        Returns:
            完整思考文本
        """
        if not self._current_thought_id:
            return ""

        with self._lock:
            # 输出缓冲区剩余内容
            if self._buffer:
                self._emit_chunk(self._buffer, is_final=True)
                self._buffer = ""
            elif self._buffer_mode == "full":
                self._emit_chunk(self._current_text, is_final=True)

            full_text = self._current_text
            thought_id = self._current_thought_id
            self._current_thought_id = None
            self._current_text = ""

        if self._on_thought_end:
            try:
                self._on_thought_end(thought_id, full_text)
            except Exception:
                pass

        return full_text

    def cancel_thought(self) -> None:
        """取消当前思考"""
        with self._lock:
            self._current_thought_id = None
            self._current_text = ""
            self._buffer = ""
            self._chunk_index = 0

    def _emit_chunk(self, text: str, is_final: bool) -> None:
        """发射 chunk"""
        if not self._on_chunk or not text:
            return

        chunk = ThoughtChunk(
            text=text,
            thought_id=self._current_thought_id or "",
            chunk_index=self._chunk_index,
            is_final=is_final,
        )

        try:
            self._on_chunk(chunk)
        except Exception:
            pass

    @property
    def current_text(self) -> str:
        """当前累积的文本"""
        with self._lock:
            return self._current_text

    @property
    def is_active(self) -> bool:
        """是否有活跃的思考"""
        with self._lock:
            return self._current_thought_id is not None


# ============================================================================
# 中断响应处理器（阶段 P.1.2）
# ============================================================================

class InterruptionHandler:
    """中断响应处理器

    允许用户随时打断 Agent 执行，优雅保存进度。

    特性：
    - 线程安全的中断标志
    - 中断原因记录
    - 中断回调（保存进度等）
    - 中断后可查询状态

    使用方式：
        handler = InterruptionHandler(on_interrupt=save_progress)
        # 在 Agent 循环中检查
        for step in range(max_steps):
            if handler.check():
                break
            ...
        # 用户触发中断
        handler.interrupt("用户取消")
    """

    def __init__(
        self,
        on_interrupt: Optional[Callable[[str], None]] = None,
        check_interval: float = 0.1,
    ):
        """初始化

        Args:
            on_interrupt: 中断回调函数（接收中断原因）
            check_interval: 检查间隔（秒）
        """
        self._interrupted = threading.Event()
        self._reason = ""
        self._interrupt_time: Optional[float] = None
        self._on_interrupt = on_interrupt
        self._check_interval = check_interval
        self._lock = threading.Lock()

    def interrupt(self, reason: str = "用户中断") -> None:
        """触发中断

        Args:
            reason: 中断原因
        """
        with self._lock:
            if self._interrupted.is_set():
                return  # 已中断
            self._interrupted.set()
            self._reason = reason
            self._interrupt_time = time.time()

        if self._on_interrupt:
            try:
                self._on_interrupt(reason)
            except Exception:
                pass

    def check(self) -> bool:
        """检查是否被中断

        Returns:
            True 表示已被中断
        """
        return self._interrupted.is_set()

    async def check_async(self) -> bool:
        """异步检查（带间隔）"""
        if self._interrupted.is_set():
            return True
        await asyncio.sleep(self._check_interval)
        return self._interrupted.is_set()

    def wait_for_interrupt(self, timeout: Optional[float] = None) -> bool:
        """等待中断

        Args:
            timeout: 超时秒数（None 表示无限等待）

        Returns:
            True 表示被中断，False 表示超时
        """
        return self._interrupted.wait(timeout)

    def reset(self) -> None:
        """重置中断状态"""
        with self._lock:
            self._interrupted.clear()
            self._reason = ""
            self._interrupt_time = None

    @property
    def is_interrupted(self) -> bool:
        """是否被中断"""
        return self._interrupted.is_set()

    @property
    def reason(self) -> str:
        """中断原因"""
        return self._reason

    @property
    def interrupt_time(self) -> Optional[float]:
        """中断时间"""
        return self._interrupt_time

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "interrupted": self._interrupted.is_set(),
            "reason": self._reason,
            "interrupt_time": self._interrupt_time,
            "elapsed_since_interrupt": (
                time.time() - self._interrupt_time
                if self._interrupt_time else None
            ),
        }


# ============================================================================
# 工具调用进度跟踪器（阶段 P.1.3）
# ============================================================================

@dataclass
class ToolCallProgress:
    """工具调用进度"""
    tool_name: str
    status: str = "pending"  # pending / running / done / failed / timeout
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    progress: float = 0.0  # 0.0 - 1.0
    message: str = ""
    args_preview: str = ""
    result_preview: str = ""
    error: str = ""

    @property
    def duration(self) -> float:
        """耗时"""
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.time()
        return end - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "duration": round(self.duration, 3),
            "progress": round(self.progress, 2),
            "message": self.message,
            "error": self.error,
        }


class ProgressTracker:
    """工具调用进度跟踪器

    实时跟踪工具执行状态，支持多工具并行。

    使用方式：
        tracker = ProgressTracker(on_update=print_status)
        call_id = tracker.start("read_file", {"path": "/tmp/test.txt"})
        tracker.update(call_id, progress=0.5, message="读取中...")
        tracker.complete(call_id, result="文件内容")
        # 或失败
        tracker.fail(call_id, error="文件不存在")
    """

    def __init__(
        self,
        on_update: Optional[Callable[[str, ToolCallProgress], None]] = None,
    ):
        """初始化

        Args:
            on_update: 进度更新回调 (call_id, progress)
        """
        self._calls: Dict[str, ToolCallProgress] = {}
        self._on_update = on_update
        self._lock = threading.RLock()

    def start(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> str:
        """开始跟踪工具调用

        Args:
            tool_name: 工具名
            args: 调用参数

        Returns:
            call_id
        """
        import uuid
        call_id = str(uuid.uuid4())[:8]

        # 构造参数预览
        args_preview = ""
        if args:
            args_preview = ", ".join(
                f"{k}={str(v)[:50]}" for k, v in list(args.items())[:3]
            )

        progress = ToolCallProgress(
            tool_name=tool_name,
            status="running",
            start_time=time.time(),
            args_preview=args_preview,
        )

        with self._lock:
            self._calls[call_id] = progress

        self._notify(call_id, progress)
        return call_id

    def update(
        self,
        call_id: str,
        progress: float = 0.0,
        message: str = "",
    ) -> None:
        """更新进度

        Args:
            call_id: 调用 ID
            progress: 进度 0.0-1.0
            message: 进度消息
        """
        with self._lock:
            call = self._calls.get(call_id)
            if call:
                call.progress = max(0.0, min(1.0, progress))
                if message:
                    call.message = message

        if call:
            self._notify(call_id, call)

    def complete(
        self,
        call_id: str,
        result: str = "",
    ) -> None:
        """标记完成

        Args:
            call_id: 调用 ID
            result: 结果预览
        """
        with self._lock:
            call = self._calls.get(call_id)
            if call:
                call.status = "done"
                call.end_time = time.time()
                call.progress = 1.0
                call.result_preview = result[:200] if result else ""

        if call:
            self._notify(call_id, call)

    def fail(
        self,
        call_id: str,
        error: str,
    ) -> None:
        """标记失败

        Args:
            call_id: 调用 ID
            error: 错误信息
        """
        with self._lock:
            call = self._calls.get(call_id)
            if call:
                call.status = "failed"
                call.end_time = time.time()
                call.error = error

        if call:
            self._notify(call_id, call)

    def timeout(self, call_id: str) -> None:
        """标记超时"""
        with self._lock:
            call = self._calls.get(call_id)
            if call:
                call.status = "timeout"
                call.end_time = time.time()
                call.error = "执行超时"

        if call:
            self._notify(call_id, call)

    def get_progress(self, call_id: str) -> Optional[ToolCallProgress]:
        """获取单个调用进度"""
        with self._lock:
            return self._calls.get(call_id)

    def get_all_progress(self) -> Dict[str, ToolCallProgress]:
        """获取所有调用进度"""
        with self._lock:
            return dict(self._calls)

    def get_active_calls(self) -> List[str]:
        """获取活跃的调用 ID"""
        with self._lock:
            return [
                cid for cid, call in self._calls.items()
                if call.status == "running"
            ]

    def render_progress_bar(self, call_id: str, width: int = 30) -> str:
        """渲染进度条

        Args:
            call_id: 调用 ID
            width: 进度条宽度

        Returns:
            进度条字符串
        """
        with self._lock:
            call = self._calls.get(call_id)
            if not call:
                return ""

        filled = int(width * call.progress)
        bar = "█" * filled + "░" * (width - filled)
        percentage = int(call.progress * 100)

        status_icon = {
            "pending": "⏳",
            "running": "🔄",
            "done": "✅",
            "failed": "❌",
            "timeout": "⏱️",
        }.get(call.status, "?")

        return f"{status_icon} [{bar}] {percentage}% {call.tool_name} ({call.duration:.1f}s)"

    def render_summary(self) -> str:
        """渲染所有调用的摘要"""
        with self._lock:
            calls = list(self._calls.values())

        if not calls:
            return "无工具调用"

        lines = [f"工具调用摘要 ({len(calls)} 个):"]
        for call in calls:
            status_icon = {
                "pending": "⏳",
                "running": "🔄",
                "done": "✅",
                "failed": "❌",
                "timeout": "⏱️",
            }.get(call.status, "?")
            lines.append(
                f"  {status_icon} {call.tool_name}: {call.status} "
                f"({call.duration:.2f}s)"
            )
            if call.error:
                lines.append(f"     错误: {call.error[:100]}")

        return "\n".join(lines)

    def clear(self) -> None:
        """清空所有记录"""
        with self._lock:
            self._calls.clear()

    def _notify(self, call_id: str, progress: ToolCallProgress) -> None:
        """通知回调"""
        if self._on_update:
            try:
                self._on_update(call_id, progress)
            except Exception:
                pass

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            calls = list(self._calls.values())

        total = len(calls)
        done = sum(1 for c in calls if c.status == "done")
        failed = sum(1 for c in calls if c.status == "failed")
        running = sum(1 for c in calls if c.status == "running")
        total_duration = sum(c.duration for c in calls)

        return {
            "total": total,
            "done": done,
            "failed": failed,
            "running": running,
            "total_duration": round(total_duration, 3),
            "average_duration": round(total_duration / total, 3) if total else 0,
        }


# ============================================================================
# 全局实例管理
# ============================================================================

_default_emitter: Optional[StreamingThoughtEmitter] = None
_default_interrupt_handler: Optional[InterruptionHandler] = None
_default_progress_tracker: Optional[ProgressTracker] = None


def get_streaming_emitter(
    on_chunk: Optional[Callable[[ThoughtChunk], None]] = None,
) -> StreamingThoughtEmitter:
    """获取全局流式发射器"""
    global _default_emitter
    if _default_emitter is None:
        _default_emitter = StreamingThoughtEmitter(on_chunk=on_chunk)
    return _default_emitter


def get_interrupt_handler() -> InterruptionHandler:
    """获取全局中断处理器"""
    global _default_interrupt_handler
    if _default_interrupt_handler is None:
        _default_interrupt_handler = InterruptionHandler()
    return _default_interrupt_handler


def get_progress_tracker(
    on_update: Optional[Callable[[str, ToolCallProgress], None]] = None,
) -> ProgressTracker:
    """获取全局进度跟踪器"""
    global _default_progress_tracker
    if _default_progress_tracker is None:
        _default_progress_tracker = ProgressTracker(on_update=on_update)
    return _default_progress_tracker


def reset_streaming() -> None:
    """重置所有流式组件"""
    global _default_emitter, _default_interrupt_handler, _default_progress_tracker
    _default_emitter = None
    _default_interrupt_handler = None
    _default_progress_tracker = None


__all__ = [
    "ThoughtChunk",
    "StreamingThoughtEmitter",
    "InterruptionHandler",
    "ToolCallProgress",
    "ProgressTracker",
    "get_streaming_emitter",
    "get_interrupt_handler",
    "get_progress_tracker",
    "reset_streaming",
]
