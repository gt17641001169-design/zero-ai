"""
zeroai-tui: ZeroAI Chat Interface
Simplified chat UI using zeroai-tui framework
"""
import sys
import os
import asyncio
from typing import List, Optional, Callable

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from zeroai_tui.terminal import Terminal, Color
from zeroai_tui.renderer import get_renderer, Style
from zeroai_tui.components import Component, Text, Box, Input, ScrollView
from zeroai_tui.rich_components import Markdown, CodeBlock, StatusLine
from zeroai_tui.app import App


class MessageInput(Input):
    """Message input with history support"""
    
    def __init__(self, placeholder: str = "", on_submit: Optional[Callable] = None):
        super().__init__(placeholder=placeholder, on_submit=on_submit)
        self.history: List[str] = []
        self.history_index = -1
    
    def handle_key(self, key: str) -> bool:
        """Handle key input with history"""
        # Enter to submit
        if key == '\r' or key == '\n':
            if self.value.strip():
                self.history.append(self.value)
                self.history_index = len(self.history)
            return super().handle_key(key)
        
        # Up/Down for history
        if key == '\x1b':
            # Escape sequence - need to read more
            return False
        
        return super().handle_key(key)


class ChatMessage(Component):
    """Chat message component"""
    
    def __init__(self, 
                 role: str, 
                 content: str, 
                 expert: str = "",
                 id: Optional[str] = None):
        super().__init__(id)
        self.role = role
        self.content = content
        self.expert = expert
        self._is_streaming = False
    
    def render(self):
        """Render chat message"""
        if not self.visible:
            return

        renderer = get_renderer()
        row, col, width, height = self.y, self.x, self.width, self.height

        if self.role == "user":
            # User message
            header = "  ┌─ 你"
            header_style = Style(bold=True, fg=Color.BRIGHT_GREEN)
        else:
            # AI message
            expert_label = f" · {self.expert}" if self.expert else ""
            header = f"  ┌─ 助手{expert_label}"
            header_style = Style(bold=True, fg=Color.CYAN)

        # Render header
        renderer.write(row, col, header, header_style)

        # Render content
        lines = self.content.split('\n')
        current_row = row + 1

        for line in lines:
            if current_row >= row + height - 1:
                break

            # Truncate long lines
            display_line = line[:width - 4] if len(line) > width - 4 else line

            if self.role == "user":
                renderer.write(current_row, col + 2, display_line, Style(fg=Color.WHITE))
            else:
                renderer.write(current_row, col + 2, display_line, Style(fg=Color.BRIGHT_WHITE))

            current_row += 1

        # Render footer
        if current_row < row + height:
            renderer.write(current_row, col, "  └" + "─" * (width - 4), Style(fg=Color.DIM))


class ZeroAIChat(App):
    """ZeroAI Chat Interface using zeroai-tui"""
    
    def __init__(self):
        super().__init__()
        self.messages: List[ChatMessage] = []
        self.input_value = ""
        self._streaming = False
        self._current_expert = ""
        
        # Status bar (created early for set_status calls)
        self.status_bar = StatusLine(text="Initializing...")
        
        # Callbacks
        self._on_send: Optional[Callable] = None
        self._on_exit: Optional[Callable] = None
    
    def set_callbacks(self, 
                      on_send: Optional[Callable] = None,
                      on_exit: Optional[Callable] = None):
        """Set callback functions"""
        self._on_send = on_send
        self._on_exit = on_exit
    
    def build(self) -> Component:
        """Build chat UI"""
        # Message container
        self.message_container = ScrollView(id="messages")
        
        # Add welcome message
        welcome = ChatMessage("ai", 
            "你好！我是 ZeroAI 助手。\n\n"
            "我可以帮你处理各种任务：\n"
            "  • 代码编写、调试、重构\n"
            "  • 数学证明、逻辑推理\n"
            "  • 文档写作、翻译\n"
            "  • 学术研究、文献检索\n\n"
            "输入消息开始对话，Ctrl+C 退出。")
        self.message_container.add_child(welcome)
        
        # Input field
        self.input_field = MessageInput(
            placeholder="输入消息... (Enter发送, Ctrl+C退出)",
            on_submit=self._on_submit
        )
        
        return Box(
            children=[
                self.message_container,
                self.input_field,
                self.status_bar
            ]
        )
    
    def _on_submit(self, text: str):
        """Handle message submission"""
        if not text.strip():
            return
        
        # Add user message
        user_msg = ChatMessage("user", text)
        self.messages.append(user_msg)
        self.message_container.add_child(user_msg)
        
        # Clear input
        self.input_value = ""
        self.input_field.value = ""
        self.input_field.cursor_pos = 0
        
        # Call callback
        if self._on_send:
            self._on_send(text)
        
        # Scroll to bottom
        self.message_container.scroll_to_bottom()
    
    def add_ai_message(self, content: str, expert: str = ""):
        """Add AI message"""
        ai_msg = ChatMessage("ai", content, expert)
        self.messages.append(ai_msg)
        self.message_container.add_child(ai_msg)
        self.message_container.scroll_to_bottom()
    
    def update_last_message(self, content: str):
        """Update last AI message (for streaming)"""
        if self.messages and self.messages[-1].role == "ai":
            self.messages[-1].content = content
            self.message_container.mark_dirty()
    
    def set_status(self, text: str):
        """Update status bar"""
        self.status_bar.set_text(text)
    
    def _handle_input(self, key: str):
        """Handle global input"""
        # Ctrl+C to exit
        if key == '\x03':
            if self._on_exit:
                self._on_exit()
            self.stop()
            return
        
        # Pass to parent
        super()._handle_input(key)


def main():
    """Run ZeroAI Chat"""
    print("Starting ZeroAI Chat...")
    print("Press Ctrl+C to exit")
    print()
    
    try:
        app = ZeroAIChat()
        
        # Demo: add some messages
        app.add_ai_message("欢迎使用 ZeroAI！")
        
        app.run()
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
