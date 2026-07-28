"""思维链可视化增强（阶段 G.1）

为 Agent Loop 提供更丰富的思维链展示能力：
1. 卡片式思维链：每个 Thought 渲染为带边框的卡片
2. 进度条：显示当前执行进度
3. 状态图标：成功/失败/进行中的图标标识
4. 耗时统计：每步耗时和总耗时
5. 颜色编码：不同 action_type 用不同颜色

设计原则：
- 增量追加：不修改 agent.py 的 Thought 类
- 可选使用：TUI 层可选择使用本模块的渲染
- 终端兼容：使用 ANSI 转义序列，兼容主流终端

使用方式：
    from zeroai.core.thought_visualizer import ThoughtVisualizer, render_thought_card
    viz = ThoughtVisualizer()
    # 渲染单个思维卡片
    card = viz.render_card(thought)
    # 渲染完整思维链
    chain_text = viz.render_chain(thought_chain)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ============================================================================
# ANSI 颜色常量
# ============================================================================

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"


# ============================================================================
# action_type 颜色映射
# ============================================================================

ACTION_COLORS = {
    "tool_call": Color.CYAN,
    "final_answer": Color.GREEN,
    "ask_user": Color.YELLOW,
    "reflect": Color.MAGENTA,
    "plan": Color.BLUE,
    "error": Color.RED,
}

ACTION_ICONS = {
    "tool_call": "[*]",
    "final_answer": "[=]",
    "ask_user": "[?]",
    "reflect": "[~]",
    "plan": "[>]",
    "error": "[!]",
}


# ============================================================================
# 可视化器
# ============================================================================

class ThoughtVisualizer:
    """思维链可视化渲染器"""

    def __init__(self, width: int = 80):
        self._width = max(60, width)
        self._start_time: Optional[float] = None

    @property
    def width(self) -> int:
        return self._width

    def render_card(self, thought: Any) -> str:
        """渲染单个思维节点为卡片

        Args:
            thought: Thought 对象或 dict

        Returns:
            卡片字符串
        """
        # 提取字段（兼容 Thought dataclass 和 dict）
        if isinstance(thought, dict):
            step = thought.get("step", 0)
            thought_text = thought.get("thought", "")
            action_type = thought.get("action_type", "")
            tool_name = thought.get("tool_name", "")
            args = thought.get("args", {})
            result = thought.get("result", "")
            reflection = thought.get("reflection", "")
            success = thought.get("success", True)
            timestamp = thought.get("timestamp", 0)
        else:
            step = getattr(thought, "step", 0)
            thought_text = getattr(thought, "thought", "")
            action_type = getattr(thought, "action_type", "")
            tool_name = getattr(thought, "tool_name", "")
            args = getattr(thought, "args", {})
            result = getattr(thought, "result", "")
            reflection = getattr(thought, "reflection", "")
            success = getattr(thought, "success", True)
            timestamp = getattr(thought, "timestamp", 0)

        color = ACTION_COLORS.get(action_type, Color.WHITE)
        icon = ACTION_ICONS.get(action_type, "[ ]")
        status = f"{Color.GREEN}[OK]{Color.RESET}" if success else f"{Color.RED}[FAIL]{Color.RESET}"

        lines = []

        # 卡片顶边
        lines.append(f"{Color.DIM}{'=' * self._width}{Color.RESET}")

        # 标题行：步骤号 + 图标 + action_type + 状态
        title = f"{color}{icon} 步骤 {step}{Color.RESET} {color}{action_type}{Color.RESET} {status}"
        lines.append(title)

        # 思考内容
        if thought_text:
            lines.append(f"{Color.DIM}思考:{Color.RESET}")
            for line in self._wrap_text(thought_text, self._width - 4):
                lines.append(f"  {line}")

        # 工具调用
        if tool_name:
            lines.append(f"{Color.CYAN}工具:{Color.RESET} {tool_name}")
            if args:
                args_str = self._format_args(args)
                for line in self._wrap_text(args_str, self._width - 4):
                    lines.append(f"  {Color.DIM}{line}{Color.RESET}")

        # 结果
        if result:
            result_color = Color.GREEN if success else Color.RED
            lines.append(f"{result_color}结果:{Color.RESET}")
            result_preview = result[:500] + "..." if len(result) > 500 else result
            for line in self._wrap_text(result_preview, self._width - 4):
                lines.append(f"  {line}")

        # 反思
        if reflection:
            lines.append(f"{Color.MAGENTA}反思:{Color.RESET}")
            for line in self._wrap_text(reflection, self._width - 4):
                lines.append(f"  {line}")

        # 时间戳
        if timestamp:
            time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
            lines.append(f"{Color.DIM}时间: {time_str}{Color.RESET}")

        # 卡片底边
        lines.append(f"{Color.DIM}{'=' * self._width}{Color.RESET}")

        return "\n".join(lines)

    def render_chain(
        self,
        thought_chain: List[Any],
        show_progress: bool = True,
    ) -> str:
        """渲染完整思维链

        Args:
            thought_chain: Thought 对象列表
            show_progress: 是否显示进度条

        Returns:
            思维链字符串
        """
        if not thought_chain:
            return f"{Color.DIM}(空思维链){Color.RESET}"

        lines = []

        # 标题
        lines.append(f"{Color.BOLD}{Color.CYAN}{'=' * self._width}{Color.RESET}")
        lines.append(f"{Color.BOLD}{Color.CYAN}思维链 ({len(thought_chain)} 步){Color.RESET}")
        lines.append(f"{Color.BOLD}{Color.CYAN}{'=' * self._width}{Color.RESET}")
        lines.append("")

        # 进度条
        if show_progress and len(thought_chain) > 0:
            progress = self.render_progress(thought_chain)
            lines.append(progress)
            lines.append("")

        # 每个思维节点
        for thought in thought_chain:
            lines.append(self.render_card(thought))
            lines.append("")

        # 总结
        success_count = 0
        for t in thought_chain:
            if isinstance(t, dict):
                if t.get("success", True):
                    success_count += 1
            else:
                if getattr(t, "success", True):
                    success_count += 1
        fail_count = len(thought_chain) - success_count

        # 计算总耗时
        timestamps = []
        for t in thought_chain:
            ts = getattr(t, "timestamp", 0) if not isinstance(t, dict) else t.get("timestamp", 0)
            if ts:
                timestamps.append(ts)
        total_duration = 0.0
        if len(timestamps) >= 2:
            total_duration = timestamps[-1] - timestamps[0]

        lines.append(f"{Color.BOLD}总结:{Color.RESET}")
        lines.append(f"  总步骤: {len(thought_chain)}")
        lines.append(f"  成功: {Color.GREEN}{success_count}{Color.RESET}  失败: {Color.RED if fail_count else Color.DIM}{fail_count}{Color.RESET}")
        if total_duration > 0:
            lines.append(f"  总耗时: {total_duration:.2f}s")
        lines.append("")

        return "\n".join(lines)

    def render_progress(self, thought_chain: List[Any]) -> str:
        """渲染进度条"""
        if not thought_chain:
            return ""

        success_count = 0
        for t in thought_chain:
            if isinstance(t, dict):
                if t.get("success", True):
                    success_count += 1
            else:
                if getattr(t, "success", True):
                    success_count += 1
        total = len(thought_chain)
        success_rate = success_count / total if total > 0 else 0

        # 进度条
        bar_width = min(40, self._width - 30)
        filled = int(bar_width * success_rate)
        bar = f"{Color.GREEN}{'█' * filled}{Color.DIM}{'░' * (bar_width - filled)}{Color.RESET}"

        return f"{Color.DIM}进度:{Color.RESET} [{bar}] {success_count}/{total} ({success_rate:.0%})"

    def _render_progress(self, thought_chain: List[Any]) -> str:
        """内部进度条渲染（兼容旧接口）"""
        return self.render_progress(thought_chain)

    def _wrap_text(self, text: str, width: int) -> List[str]:
        """文本换行"""
        if not text:
            return [""]
        # 转为字符串
        text = str(text)
        lines = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            # 简单字符计数换行（不处理中文宽度）
            while len(paragraph) > width:
                lines.append(paragraph[:width])
                paragraph = paragraph[width:]
            if paragraph:
                lines.append(paragraph)
        return lines if lines else [""]

    def _format_args(self, args: Dict[str, Any]) -> str:
        """格式化参数"""
        if not args:
            return "{}"
        parts = []
        for k, v in args.items():
            v_str = str(v)
            if len(v_str) > 100:
                v_str = v_str[:100] + "..."
            parts.append(f"{k}={v_str}")
        return ", ".join(parts)


# ============================================================================
# 便捷函数
# ============================================================================

def render_thought_card(thought: Any, width: int = 80) -> str:
    """渲染单个思维卡片（便捷函数）"""
    viz = ThoughtVisualizer(width=width)
    return viz.render_card(thought)


def render_thought_chain(
    thought_chain: List[Any],
    width: int = 80,
    show_progress: bool = True,
) -> str:
    """渲染思维链（便捷函数）"""
    viz = ThoughtVisualizer(width=width)
    return viz.render_chain(thought_chain, show_progress=show_progress)


# ============================================================================
# 全局可视化器
# ============================================================================

_visualizer: Optional[ThoughtVisualizer] = None


def get_visualizer(width: int = 80) -> ThoughtVisualizer:
    """获取全局可视化器实例"""
    global _visualizer
    if _visualizer is None:
        _visualizer = ThoughtVisualizer(width=width)
    return _visualizer


__all__ = [
    "Color",
    "ACTION_COLORS",
    "ACTION_ICONS",
    "ThoughtVisualizer",
    "render_thought_card",
    "render_thought_chain",
    "get_visualizer",
]
