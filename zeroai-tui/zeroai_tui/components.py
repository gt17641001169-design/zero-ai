"""
zeroai-tui: Component system

自研 TUI 组件框架（对应你的设计图）：

核心抽象：
    - Component：所有组件基类，包含几何、样式、可见性、焦点、状态
    - Container：容器基类，负责子组件管理与 layout() 布局
    - Layout：布局策略接口（FlexLayout, StackLayout, AbsoluteLayout）
    - Event：统一事件对象（key, mouse, resize, focus 等）

设计原则：
    1. 单一职责：每个组件只负责自己的渲染和事件
    2. 父子隔离：父组件 layout() 决定子组件几何，子组件只读
    3. 脏区检测：_dirty 标记减少无效渲染
    4. 自动降级：组件系统不依赖 C/Zig 扩展，纯 Python 可运行
"""
from typing import List, Optional, Callable, Any, Dict, Tuple
from abc import ABC, abstractmethod
from .renderer import get_renderer, Style
from .terminal import Terminal, Color


# ============================================================================
# 事件系统
# ============================================================================

class Event:
    """统一事件对象

    对应你设计图中的事件处理：所有输入统一封装为 Event，
    组件通过 handle_event(event) 处理，不再直接处理 raw key string。
    """

    TYPE_KEY = "key"
    TYPE_RESIZE = "resize"
    TYPE_FOCUS = "focus"
    TYPE_BLUR = "blur"
    TYPE_MOUSE = "mouse"
    TYPE_TICK = "tick"  # 用于流式更新

    def __init__(self, event_type: str, data: Any = None, **kwargs):
        self.type = event_type
        self.data = data
        self.props = kwargs
        self._handled = False

    def is_key(self, key: str) -> bool:
        """判断是否是某个按键"""
        return self.type == self.TYPE_KEY and self.data == key

    def stop_propagation(self):
        """阻止事件继续传播"""
        self._handled = True

    def is_handled(self) -> bool:
        return self._handled

    def __repr__(self) -> str:
        return f"Event(type={self.type}, data={self.data!r})"


# ============================================================================
# 布局系统
# ============================================================================

class Layout(ABC):
    """布局策略抽象基类"""

    @abstractmethod
    def layout(self, container: 'Container'):
        """对容器内的子组件进行布局

        设置每个子组件的 x, y, width, height。
        """
        pass


class FlexLayout(Layout):
    """Flex 布局：按方向分配空间

    direction: "column"（垂直）或 "row"（水平）
    """

    def __init__(self, direction: str = "column", gap: int = 0):
        if direction not in ("row", "column"):
            raise ValueError(f"Invalid direction: {direction}")
        self.direction = direction
        self.gap = gap

    def layout(self, container: 'Container'):
        children = [c for c in container.children if c.visible]
        if not children:
            return

        if self.direction == "column":
            total_gap = self.gap * max(0, len(children) - 1)
            available_height = container.height - total_gap
            # 简单均分高度
            child_height = available_height // len(children)
            extra = available_height - child_height * len(children)

            y = container.y
            for i, child in enumerate(children):
                h = child_height + (1 if i < extra else 0)
                child.set_geometry(container.x, y, container.width, h)
                y += h + self.gap
        else:
            total_gap = self.gap * max(0, len(children) - 1)
            available_width = container.width - total_gap
            child_width = available_width // len(children)
            extra = available_width - child_width * len(children)

            x = container.x
            for i, child in enumerate(children):
                w = child_width + (1 if i < extra else 0)
                child.set_geometry(x, container.y, w, container.height)
                x += w + self.gap


class StackLayout(Layout):
    """堆叠布局：所有子组件占据整个容器空间

    用于弹窗、覆盖层、单页切换。
    """

    def layout(self, container: 'Container'):
        for child in container.children:
            if child.visible:
                child.set_geometry(container.x, container.y, container.width, container.height)


class AbsoluteLayout(Layout):
    """绝对布局：子组件自行维护 x,y,width,height，容器不干预"""

    def layout(self, container: 'Container'):
        # 绝对布局下子组件几何已预设，只需裁剪可见性
        pass


# ============================================================================
# 主题系统
# ============================================================================

class Theme:
    """统一主题/颜色系统

    对应你设计图中的主题/颜色部分。所有组件默认从 Theme 取色，
    避免颜色散落在各组件里。
    """

    # 默认 16 色配色（与 terminal.py Color 类对应）
    DEFAULT = {
        "primary": Color.CYAN,
        "secondary": Color.BRIGHT_BLACK,
        "success": Color.GREEN,
        "warning": Color.YELLOW,
        "danger": Color.RED,
        "info": Color.BLUE,
        "text": Color.WHITE,
        "text_muted": Color.BRIGHT_BLACK,
        "text_inverse": Color.BLACK,
        "bg": Color.BLACK,
        "bg_panel": Color.BRIGHT_BLACK,
        "border": Color.WHITE,
        "border_focused": Color.CYAN,
        "user_message": Color.BRIGHT_GREEN,
        "ai_message": Color.BRIGHT_WHITE,
        "header": Color.CYAN,
        "input_placeholder": Color.BRIGHT_BLACK,
    }

    _current = DEFAULT.copy()

    @classmethod
    def get(cls, key: str, default: str = "") -> str:
        """获取主题色"""
        return cls._current.get(key, default)

    @classmethod
    def set(cls, key: str, value: str):
        """设置主题色"""
        cls._current[key] = value

    @classmethod
    def update(cls, colors: Dict[str, str]):
        """批量更新主题色"""
        cls._current.update(colors)

    @classmethod
    def reset(cls):
        """重置为默认主题"""
        cls._current = cls.DEFAULT.copy()


# ============================================================================
# Component 基类
# ============================================================================

class Component:
    """所有 TUI 组件的基类

    对应你设计图中的 Component：
        - 几何属性：x, y, width, height
        - 样式属性：style
        - 状态属性：visible, focusable, focused, enabled
        - 树属性：parent, children
        - 生命周期：render(), layout(), handle_event()
    """

    def __init__(self,
                 id: Optional[str] = None,
                 x: int = 0, y: int = 0,
                 width: int = 0, height: int = 0,
                 style: Optional[Style] = None,
                 visible: bool = True,
                 focusable: bool = False,
                 enabled: bool = True):
        self.id = id
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.style = style
        self.visible = visible
        self.focusable = focusable
        self.focused = False
        self.enabled = enabled

        self.parent: Optional['Component'] = None
        self.children: List['Component'] = []
        self._dirty = True
        self._data: Dict[str, Any] = {}  # 通用数据挂载点

    # ----------------------------------------------------------------------
    # 几何管理
    # ----------------------------------------------------------------------
    def set_geometry(self, x: int, y: int, width: int, height: int):
        """设置组件几何，脏标记仅在变化时触发"""
        if (self.x != x or self.y != y or
            self.width != width or self.height != height):
            self.x = x
            self.y = y
            self.width = width
            self.height = height
            self.mark_dirty()

    def get_geometry(self) -> Tuple[int, int, int, int]:
        """获取组件几何 (x, y, width, height)"""
        return (self.x, self.y, self.width, self.height)

    # ----------------------------------------------------------------------
    # 树管理
    # ----------------------------------------------------------------------
    def add_child(self, child: 'Component'):
        """添加子组件"""
        if child.parent is not None:
            child.parent.remove_child(child)
        child.parent = self
        self.children.append(child)
        self.mark_dirty()

    def remove_child(self, child: 'Component'):
        """移除子组件"""
        if child in self.children:
            child.parent = None
            self.children.remove(child)
            self.mark_dirty()

    def remove_all_children(self):
        """移除所有子组件"""
        for child in self.children:
            child.parent = None
        self.children.clear()
        self.mark_dirty()

    def find_by_id(self, id: str) -> Optional['Component']:
        """通过 id 递归查找组件"""
        if self.id == id:
            return self
        for child in self.children:
            found = child.find_by_id(id)
            if found:
                return found
        return None

    # ----------------------------------------------------------------------
    # 脏区管理
    # ----------------------------------------------------------------------
    def mark_dirty(self):
        """标记组件需要重绘"""
        self._dirty = True
        if self.parent:
            self.parent.mark_dirty()

    def mark_clean(self):
        """清除脏标记"""
        self._dirty = False
        for child in self.children:
            child.mark_clean()

    def is_dirty(self) -> bool:
        """判断是否需要重绘（递归检查子组件）"""
        if self._dirty:
            return True
        return any(child.is_dirty() for child in self.children)

    # ----------------------------------------------------------------------
    # 焦点管理
    # ----------------------------------------------------------------------
    def set_focus(self, focused: bool = True):
        """设置焦点状态"""
        if self.focused != focused:
            self.focused = focused
            self.mark_dirty()

    def focus_next(self) -> Optional['Component']:
        """焦点移动到下一个可聚焦组件"""
        return self._focus_step(forward=True)

    def focus_prev(self) -> Optional['Component']:
        """焦点移动到上一个可聚焦组件"""
        return self._focus_step(forward=False)

    def _focus_step(self, forward: bool) -> Optional['Component']:
        """遍历树寻找下一个可聚焦组件"""
        all_focusable = []
        self._collect_focusable(all_focusable)
        if not all_focusable:
            return None

        try:
            idx = all_focusable.index(self)
        except ValueError:
            idx = -1

        if forward:
            next_idx = (idx + 1) % len(all_focusable)
        else:
            next_idx = (idx - 1) % len(all_focusable)

        # 清除旧焦点
        for comp in all_focusable:
            comp.set_focus(False)
        # 设置新焦点
        new_focus = all_focusable[next_idx]
        new_focus.set_focus(True)
        return new_focus

    def _collect_focusable(self, out: List['Component']):
        """收集所有可见且可聚焦的组件"""
        if self.visible and self.focusable:
            out.append(self)
        for child in self.children:
            child._collect_focusable(out)

    # ----------------------------------------------------------------------
    # 渲染与事件（子类覆盖）
    # ----------------------------------------------------------------------
    def render(self):
        """渲染组件到缓冲区

        子类应使用 self.x, self.y, self.width, self.height 作为渲染区域。
        默认实现递归渲染子组件。
        """
        if not self.visible:
            return
        for child in self.children:
            if child.visible:
                child.render()

    def handle_event(self, event: Event) -> bool:
        """处理事件

        返回 True 表示事件已处理，不再向上/下传播。
        默认实现将事件传递给子组件（深度优先），最后调用 on_event。
        """
        if not self.enabled or not self.visible:
            return False
        if event.is_handled():
            return True

        # 子组件优先处理
        for child in self.children:
            if child.handle_event(event):
                return True

        # 自身处理
        return self.on_event(event)

    def on_event(self, event: Event) -> bool:
        """子类覆盖此方法处理事件"""
        return False

    def layout(self):
        """对自身和子组件进行布局

        默认实现递归调用子组件 layout()。
        容器类应覆盖此方法。
        """
        for child in self.children:
            child.layout()

    def tick(self):
        """每帧调用（用于流式更新、动画等）"""
        pass


# ============================================================================
# Container 容器基类
# ============================================================================

class Container(Component):
    """容器基类

    对应你设计图中的 Container：负责子组件管理与 layout() 布局。
    """

    def __init__(self,
                 children: Optional[List[Component]] = None,
                 layout: Optional[Layout] = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.layout_strategy = layout or FlexLayout("column")

        if children:
            for child in children:
                self.add_child(child)

    def add_child(self, child: Component):
        """添加子组件后自动标记需要重新布局"""
        super().add_child(child)
        self.mark_dirty()

    def remove_child(self, child: Component):
        """移除子组件后自动标记需要重新布局"""
        super().remove_child(child)
        self.mark_dirty()

    def set_layout(self, layout: Layout):
        """切换布局策略"""
        self.layout_strategy = layout
        self.mark_dirty()

    def layout(self):
        """执行布局策略，然后递归子组件"""
        self.layout_strategy.layout(self)
        for child in self.children:
            child.layout()

    def render(self):
        """容器默认先渲染自己背景/边框，再渲染子组件"""
        if not self.visible:
            return
        super().render()


# ============================================================================
# 基础组件
# ============================================================================

class Text(Component):
    """文本显示组件"""

    def __init__(self,
                 text: str = "",
                 style: Optional[Style] = None,
                 wrap: bool = True,
                 **kwargs):
        super().__init__(**kwargs)
        self.text = text
        self.style = style or Style(fg=Theme.get("text"))
        self.wrap = wrap

    @property
    def content(self) -> str:
        """内容别名，与 Markdown/CodeBlock 保持一致"""
        return self.text

    @content.setter
    def content(self, value: str):
        self.set_text(value)

    def set_text(self, text: str):
        """更新文本"""
        if self.text != text:
            self.text = text
            self.mark_dirty()

    def render(self):
        """渲染文本"""
        if not self.visible:
            return

        renderer = get_renderer()

        if self.wrap:
            lines = self._wrap_text(self.text, self.width)
        else:
            lines = [self.text]

        for i, line in enumerate(lines[:self.height]):
            renderer.write(self.y + i, self.x, line, self.style)

    def _wrap_text(self, text: str, width: int) -> List[str]:
        """按宽度自动换行"""
        if width <= 0:
            return []
        if len(text) <= width:
            return [text]

        lines = []
        words = text.split()
        current_line = []
        current_length = 0

        for word in words:
            word_len = len(word)
            if not current_line:
                current_line.append(word)
                current_length = word_len
            elif current_length + 1 + word_len <= width:
                current_line.append(word)
                current_length += 1 + word_len
            else:
                lines.append(" ".join(current_line))
                current_line = [word]
                current_length = word_len

        if current_line:
            lines.append(" ".join(current_line))

        return lines if lines else [text[:width]]


class Box(Container):
    """带边框/背景的盒子容器"""

    def __init__(self,
                 children: Optional[List[Component]] = None,
                 border: bool = False,
                 title: str = "",
                 border_style: Optional[Style] = None,
                 fill: bool = False,
                 fill_char: str = " ",
                 fill_style: Optional[Style] = None,
                 **kwargs):
        super().__init__(children=children, **kwargs)
        self.border = border
        self.title = title
        self.border_style = border_style or Style(fg=Theme.get("border"))
        self.fill = fill
        self.fill_char = fill_char
        self.fill_style = fill_style or Style(fg=Theme.get("text_muted"))

    def render(self):
        """渲染边框、背景和子组件"""
        if not self.visible:
            return

        renderer = get_renderer()
        x, y, w, h = self.x, self.y, self.width, self.height

        if w <= 0 or h <= 0:
            return

        # 背景填充
        if self.fill:
            for row in range(h):
                renderer.write(y + row, x, self.fill_char * w, self.fill_style)

        # 边框
        if self.border and w >= 2 and h >= 2:
            self._draw_border(renderer, x, y, w, h)

        # 子组件渲染
        for child in self.children:
            if child.visible:
                child.render()

    def _draw_border(self, renderer, x: int, y: int, w: int, h: int):
        """绘制边框"""
        style = self.border_style
        if self.focused:
            style = Style(fg=Theme.get("border_focused"), bold=True)

        # 顶部（含标题）
        if self.title:
            title_text = f" {self.title} "
            title_len = len(title_text)
            inner = w - 2
            left_len = max(0, (inner - title_len) // 2)
            right_len = max(0, inner - left_len - title_len)
            top = "┌" + "─" * left_len + title_text + "─" * right_len + "┐"
        else:
            top = "┌" + "─" * (w - 2) + "┐"
        renderer.write(y, x, top[:w], style)

        # 两侧
        for row in range(1, h - 1):
            renderer.put(y + row, x, "│", style)
            renderer.put(y + row, x + w - 1, "│", style)

        # 底部
        bottom = "└" + "─" * (w - 2) + "┘"
        renderer.write(y + h - 1, x, bottom[:w], style)


class Input(Component):
    """输入框组件"""

    def __init__(self,
                 placeholder: str = "",
                 on_submit: Optional[Callable[[str], None]] = None,
                 on_change: Optional[Callable[[str], None]] = None,
                 password: bool = False,
                 **kwargs):
        super().__init__(focusable=True, **kwargs)
        self.placeholder = placeholder
        self.value = ""
        self.cursor_pos = 0
        self.scroll_offset = 0
        self.on_submit = on_submit
        self.on_change = on_change
        self.password = password

    def set_value(self, value: str):
        """设置输入值"""
        self.value = value
        self.cursor_pos = min(self.cursor_pos, len(value))
        self.mark_dirty()

    def clear(self):
        """清空输入"""
        self.value = ""
        self.cursor_pos = 0
        self.scroll_offset = 0
        self.mark_dirty()

    def render(self):
        """渲染输入框"""
        if not self.visible:
            return

        renderer = get_renderer()
        x, y, w, h = self.x, self.y, self.width, self.height

        if w <= 0 or h <= 0:
            return

        # 计算可见文本
        display_text = self.value if self.value else self.placeholder
        if self.password:
            display_text = "*" * len(display_text)

        # 水平滚动：保证光标可见
        max_visible = max(0, w - 2)
        if self.cursor_pos > self.scroll_offset + max_visible:
            self.scroll_offset = self.cursor_pos - max_visible
        elif self.cursor_pos < self.scroll_offset:
            self.scroll_offset = self.cursor_pos

        visible_text = display_text[self.scroll_offset:self.scroll_offset + max_visible]

        # 样式
        if self.value:
            style = Style(fg=Theme.get("text"))
        else:
            style = Style(fg=Theme.get("input_placeholder"), dim=True)

        # 绘制输入框边框
        border_style = Style(fg=Theme.get("border_focused" if self.focused else "border"))
        renderer.write(y, x, "│", border_style)
        renderer.write(y, x + 1, visible_text, style)
        renderer.write(y, x + w - 1, "│", border_style)

        # 光标
        if self.focused:
            cursor_col = x + 1 + (self.cursor_pos - self.scroll_offset)
            if x + 1 <= cursor_col < x + w - 1:
                Terminal.move_cursor(y, cursor_col)

    def handle_event(self, event: Event) -> bool:
        """处理输入事件"""
        if not self.enabled or not self.visible:
            return False
        if not self.focused:
            return False

        if event.type != Event.TYPE_KEY:
            return super().handle_event(event)

        key = event.data

        if key == '\r' or key == '\n':
            if self.on_submit:
                self.on_submit(self.value)
            event.stop_propagation()
            return True

        elif key == '\x7f' or key == '\x08':  # Backspace
            if self.cursor_pos > 0:
                self.value = self.value[:self.cursor_pos - 1] + self.value[self.cursor_pos:]
                self.cursor_pos -= 1
                self._notify_change()
                self.mark_dirty()
            event.stop_propagation()
            return True

        elif key == '\x15':  # Ctrl+U 清空
            self.clear()
            event.stop_propagation()
            return True

        elif key == '\x01':  # Ctrl+A 行首
            self.cursor_pos = 0
            self.mark_dirty()
            event.stop_propagation()
            return True

        elif key == '\x05':  # Ctrl+E 行尾
            self.cursor_pos = len(self.value)
            self.mark_dirty()
            event.stop_propagation()
            return True

        elif key == '\x1b':  # Escape 序列（箭头键等）
            # 由 App 读取完整转义序列后重新分发
            return False

        elif len(key) == 1 and key.isprintable():
            self.value = self.value[:self.cursor_pos] + key + self.value[self.cursor_pos:]
            self.cursor_pos += 1
            self._notify_change()
            self.mark_dirty()
            event.stop_propagation()
            return True

        return super().handle_event(event)

    def _notify_change(self):
        """触发 on_change 回调"""
        if self.on_change:
            self.on_change(self.value)


class ScrollView(Container):
    """滚动视图容器"""

    def __init__(self,
                 children: Optional[List[Component]] = None,
                 direction: str = "vertical",
                 show_scrollbar: bool = True,
                 **kwargs):
        super().__init__(children=children, layout=AbsoluteLayout(), **kwargs)
        self.direction = direction
        self.scroll_offset = 0
        self.show_scrollbar = show_scrollbar

    def add_child(self, child: Component):
        """添加子组件后自动滚动到底部"""
        super().add_child(child)
        self.scroll_to_bottom()

    def render(self):
        """渲染滚动视图"""
        if not self.visible:
            return

        renderer = get_renderer()
        x, y, w, h = self.x, self.y, self.width, self.height

        if w <= 0 or h <= 0:
            return

        # 子组件渲染（按滚动偏移裁剪）
        if self.direction == "vertical":
            self._render_vertical(renderer, x, y, w, h)
        else:
            self._render_horizontal(renderer, x, y, w, h)

        # 滚动条
        if self.show_scrollbar:
            self._draw_scrollbar(renderer, x, y, w, h)

    def _render_vertical(self, renderer, x: int, y: int, w: int, h: int):
        """垂直滚动渲染"""
        # 将子组件按 y 偏移
        for child in self.children:
            if not child.visible:
                continue
            # 计算子组件在可视区域内的相对位置
            child.y = y + (child.y - self.scroll_offset)
            child.x = x
            child.width = w - (1 if self.show_scrollbar else 0)
            if child.y + child.height > y and child.y < y + h:
                child.render()

    def _render_horizontal(self, renderer, x: int, y: int, w: int, h: int):
        """水平滚动渲染"""
        for child in self.children:
            if not child.visible:
                continue
            child.x = x + (child.x - self.scroll_offset)
            child.y = y
            child.height = h
            if child.x + child.width > x and child.x < x + w:
                child.render()

    def _draw_scrollbar(self, renderer, x: int, y: int, w: int, h: int):
        """绘制简单滚动条"""
        if len(self.children) == 0:
            return

        total = max(1, len(self.children))
        thumb_size = max(1, h * h // total)
        thumb_pos = min(h - thumb_size, self.scroll_offset * h // total)

        scrollbar_x = x + w - 1
        bar_style = Style(fg=Theme.get("secondary"))
        thumb_style = Style(fg=Theme.get("border"))

        for row in range(h):
            if thumb_pos <= row < thumb_pos + thumb_size:
                renderer.put(y + row, scrollbar_x, "█", thumb_style)
            else:
                renderer.put(y + row, scrollbar_x, "│", bar_style)

    def scroll_up(self, amount: int = 1):
        """向上滚动"""
        self.scroll_offset = max(0, self.scroll_offset - amount)
        self.mark_dirty()

    def scroll_down(self, amount: int = 1):
        """向下滚动"""
        max_offset = max(0, len(self.children) - 1)
        self.scroll_offset = min(max_offset, self.scroll_offset + amount)
        self.mark_dirty()

    def scroll_to_bottom(self):
        """滚动到底部"""
        self.scroll_offset = max(0, len(self.children) - 1)
        self.mark_dirty()


class Button(Component):
    """按钮组件"""

    def __init__(self,
                 text: str = "",
                 on_click: Optional[Callable] = None,
                 **kwargs):
        super().__init__(focusable=True, **kwargs)
        self.text = text
        self.on_click = on_click

    def render(self):
        """渲染按钮"""
        if not self.visible:
            return

        renderer = get_renderer()
        style = Style(
            bold=True,
            fg=Theme.get("text_inverse" if self.focused else "text"),
            bg=Theme.get("primary" if self.focused else "bg_panel")
        )
        text = f" {self.text[:self.width-2]} ".center(self.width)
        renderer.write(self.y, self.x, text, style)

    def handle_event(self, event: Event) -> bool:
        """处理按钮事件"""
        if event.type == Event.TYPE_KEY and event.data in ('\r', '\n', ' '):
            if self.on_click:
                self.on_click()
            event.stop_propagation()
            return True
        return super().handle_event(event)


class Spacer(Component):
    """空白占位组件"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def render(self):
        pass


class HorizontalLine(Component):
    """水平分隔线"""

    def __init__(self,
                 char: str = "─",
                 style: Optional[Style] = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.char = char
        self.style = style or Style(fg=Theme.get("secondary"))

    def render(self):
        """渲染水平线"""
        if not self.visible:
            return
        renderer = get_renderer()
        renderer.write(self.y, self.x, self.char * self.width, self.style)


# ============================================================================
# 工具函数
# ============================================================================

def walk_components(root: Component) -> List[Component]:
    """遍历整棵组件树"""
    result = [root]
    for child in root.children:
        result.extend(walk_components(child))
    return result


def find_focusable(root: Component) -> Optional[Component]:
    """查找第一个可聚焦组件"""
    if root.visible and root.focusable:
        return root
    for child in root.children:
        found = find_focusable(child)
        if found:
            return found
    return None
