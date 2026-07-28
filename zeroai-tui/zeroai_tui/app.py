"""
zeroai-tui: Application framework

对应你设计图中的 App / render_frame / 事件处理：
    - App 负责组件树根管理、事件循环、统一渲染
    - render_frame() 执行完整渲染管线
    - handle_input() 将原始输入转换为 Event 对象并分发
"""
import sys
import os
from typing import Optional, Callable

from .terminal import Terminal
from .renderer import get_renderer
from .components import Component, Container, Event, FlexLayout, find_focusable


class App:
    """Base application class"""

    def __init__(self):
        self.root: Optional[Component] = None
        self.running = False
        self._on_resize: Optional[Callable] = None
        self._focused_component: Optional[Component] = None
        self._escape_buffer: str = ""

    def build(self) -> Component:
        """Build component tree (override in subclass)"""
        raise NotImplementedError

    def run(self):
        """Run application"""
        # Build component tree
        self.root = self.build()

        # Initial layout
        self._apply_layout()

        # Setup terminal
        Terminal.set_raw_mode(True)
        Terminal.set_cursor_visible(False)
        Terminal.clear()

        self.running = True

        try:
            # Initial render
            self.render_frame()

            # Event loop
            while self.running:
                # Check for resize
                new_cols, new_rows = Terminal.get_size()
                if new_cols != get_renderer().cols or new_rows != get_renderer().rows:
                    get_renderer().resize()
                    self._apply_layout()
                    if self._on_resize:
                        self._on_resize(new_cols, new_rows)
                    self.render_frame()

                # Read input
                char = Terminal.read_char()
                if char:
                    self.handle_input(char)

                # Tick components (for streaming updates)
                self._tick_components(self.root)

        finally:
            # Cleanup
            Terminal.set_cursor_visible(True)
            Terminal.set_raw_mode(False)
            Terminal.clear()

    def stop(self):
        """Stop application"""
        self.running = False

    # ----------------------------------------------------------------------
    # 渲染管线
    # ----------------------------------------------------------------------
    def render_frame(self):
        """统一渲染帧

        对应你设计图中的 render_frame：
            1. 检查是否有脏区
            2. 清空 next buffer
            3. 执行组件树 render()
            4. flush 到终端
        """
        if not self.root:
            return

        renderer = get_renderer()
        renderer.clear()

        # 渲染组件树
        self.root.render()

        # Flush to terminal
        renderer.flush()

        # 清除脏标记
        self.root.mark_clean()

    def _apply_layout(self):
        """应用布局"""
        if not self.root:
            return

        renderer = get_renderer()
        self.root.set_geometry(0, 0, renderer.cols, renderer.rows)
        self.root.layout()

        # 自动聚焦第一个可聚焦组件
        if self._focused_component is None:
            focused = find_focusable(self.root)
            if focused:
                focused.set_focus(True)
                self._focused_component = focused

    # ----------------------------------------------------------------------
    # 事件处理
    # ----------------------------------------------------------------------
    def handle_input(self, char: str):
        """处理原始输入字符

        将原始输入转换为统一 Event 对象，然后分发给组件树。
        """
        # 处理转义序列（ESC 开头）
        if char == '\x1b':
            self._escape_buffer = char
            return

        if self._escape_buffer:
            self._escape_buffer += char
            # 简单转义序列通常在 3-6 个字符内结束
            if len(self._escape_buffer) >= 2:
                seq = self._escape_buffer
                self._escape_buffer = ""

                # 解析转义序列
                key = self._parse_escape_sequence(seq)
                if key:
                    self._dispatch_key_event(key)
            return

        # 普通按键
        self._dispatch_key_event(char)

    def _parse_escape_sequence(self, seq: str) -> Optional[str]:
        """解析转义序列为逻辑键名"""
        mapping = {
            '\x1b[A': 'UP',
            '\x1b[B': 'DOWN',
            '\x1b[C': 'RIGHT',
            '\x1b[D': 'LEFT',
            '\x1b[H': 'HOME',
            '\x1b[F': 'END',
            '\x1b[3~': 'DELETE',
            '\x1b[5~': 'PAGE_UP',
            '\x1b[6~': 'PAGE_DOWN',
        }
        return mapping.get(seq)

    def _dispatch_key_event(self, key: str):
        """分发按键事件"""
        # 全局退出键
        if key == '\x03':  # Ctrl+C
            self.stop()
            return

        if key == '\x04':  # Ctrl+D
            self.stop()
            return

        # Tab 切换焦点
        if key == '\t':
            self._cycle_focus(forward=True)
            self.render_frame()
            return

        if key == '\x1b[Z':  # Shift+Tab
            self._cycle_focus(forward=False)
            self.render_frame()
            return

        # 创建事件对象
        event = Event(Event.TYPE_KEY, data=key)

        # 分发给组件树（从根开始）
        if self.root and self.root.handle_event(event):
            self.render_frame()
            return

        # 全局 resize 事件
        if key == 'RESIZE':
            resize_event = Event(Event.TYPE_RESIZE, data=(get_renderer().cols, get_renderer().rows))
            if self.root:
                self.root.handle_event(resize_event)
            self.render_frame()
            return

    def _cycle_focus(self, forward: bool):
        """切换焦点"""
        if not self._focused_component:
            self._focused_component = find_focusable(self.root)
            if self._focused_component:
                self._focused_component.set_focus(True)
            return

        new_focus = self._focused_component.focus_next() if forward else self._focused_component.focus_prev()
        if new_focus:
            self._focused_component = new_focus

    def _tick_components(self, component: Component):
        """递归调用组件 tick"""
        if component is None:
            return
        component.tick()
        for child in component.children:
            self._tick_components(child)

    def on_resize(self, callback: Callable):
        """Register resize callback"""
        self._on_resize = callback


class ChatApp(App):
    """Chat application with streaming support"""

    def __init__(self):
        super().__init__()
        self.messages = []
        self.input_value = ""
        self.input_cursor = 0
        self._streaming = False
        self._current_stream = ""

    def build(self) -> Component:
        """Build chat UI"""
        from .components import Text, Input, ScrollView

        # Message display area
        self.message_container = ScrollView(id="messages")

        # Input field
        self.input_field = Input(
            placeholder="Type a message...",
            on_submit=self._on_submit,
            id="input"
        )

        # Main layout
        root = Container(
            layout=FlexLayout("column"),
            children=[
                Text("ZeroAI v2.0", style=Style(bold=True, fg=Color.CYAN), id="title"),
                self.message_container,
                self.input_field
            ],
            id="root"
        )
        return root

    def _on_submit(self, text: str):
        """Handle message submission"""
        if text.strip():
            self.add_message("user", text)
            # TODO: Call AI and stream response

    def add_message(self, role: str, content: str):
        """Add message to chat"""
        from .components import Text
        from .renderer import Style
        from .terminal import Color

        style = Style(fg=Color.GREEN) if role == "user" else Style(fg=Color.CYAN)
        self.message_container.add_child(Text(content, style=style))
        self.message_container.scroll_to_bottom()
        self.render_frame()

    def stream_response(self, text: str):
        """Stream AI response"""
        self._streaming = True
        self._current_stream = text
        # TODO: Update UI with streaming content
