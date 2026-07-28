"""
zeroai-tui demo: Simple chat interface
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from zeroai_tui import App, Text, Box, Input, ScrollView, Style, Color


class DemoApp(App):
    """Demo chat application"""
    
    def __init__(self):
        super().__init__()
        self.messages = []
        self.input_value = ""
    
    def build(self):
        """Build demo UI"""
        # Header
        header = Text("=== ZeroAI TUI Demo ===", style=Style(bold=True, fg=Color.CYAN))
        
        # Message area
        self.message_area = ScrollView(id="messages")
        self.message_area.add_child(Text("Welcome! Type a message below.", style=Style(dim=True)))
        
        # Input
        self.input_field = Input(
            placeholder="> ",
            on_submit=self._on_submit
        )
        
        return Box(
            children=[header, self.message_area, self.input_field]
        )
    
    def _on_submit(self, text: str):
        """Handle input submission"""
        if text.strip():
            # Add user message
            self.messages.append(("user", text))
            self.message_area.add_child(
                Text(f"You: {text}", style=Style(fg=Color.GREEN))
            )
            
            # Simulate AI response
            response = f"Echo: {text}"
            self.messages.append(("ai", response))
            self.message_area.add_child(
                Text(f"AI: {response}", style=Style(fg=Color.CYAN))
            )
            
            # Scroll to bottom
            self.message_area.scroll_to_bottom()
            
            # Clear input
            self.input_value = ""
            self.input_cursor = 0


def main():
    """Run demo"""
    print("Starting zeroai-tui demo...")
    print("Press Ctrl+C to exit")
    print()
    
    try:
        app = DemoApp()
        app.run()
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
