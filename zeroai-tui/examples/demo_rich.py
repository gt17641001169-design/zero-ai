"""
zeroai-tui demo: Rich components showcase
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from zeroai_tui import App, Text, Box, ScrollView, Style, Color
from zeroai_tui import Markdown, CodeBlock, Panel, StatusLine


class DemoApp(App):
    """Demo application showcasing rich components"""
    
    def __init__(self):
        super().__init__()
    
    def build(self):
        """Build demo UI"""
        from zeroai_tui.components import Box, ScrollView
        
        # Content container
        content = ScrollView()
        
        # Title
        content.add_child(Text("zeroai-tui Rich Components Demo", style=Style(bold=True, fg=Color.CYAN)))
        content.add_child(Text("=" * 50, style=Style(fg=Color.CYAN)))
        content.add_child(Text(""))
        
        # Markdown demo
        md_content = """# Markdown Support

This is a **bold text** and this is *italic text*.

## Features
- Bullet points
- `inline code`
- [Links](https://example.com)

> Blockquotes work too!

1. Numbered lists
2. Second item
"""
        md = Markdown(md_content)
        content.add_child(Text("Markdown:", style=Style(bold=True, fg=Color.GREEN)))
        content.add_child(md)
        content.add_child(Text(""))
        
        # Code block demo
        code = '''def hello(name):
    """Say hello"""
    print(f"Hello, {name}!")
    return True

# Call the function
hello("World")'''
        
        code_block = CodeBlock(code, language="python")
        content.add_child(Text("Code Block:", style=Style(bold=True, fg=Color.GREEN)))
        content.add_child(code_block)
        content.add_child(Text(""))
        
        # Panel demo
        panel_content = Text("This is content inside a panel.\nPanels can contain any component.")
        panel = Panel(child=panel_content, title="Panel Demo")
        content.add_child(Text("Panel:", style=Style(bold=True, fg=Color.GREEN)))
        content.add_child(panel)
        content.add_child(Text(""))
        
        # Status line
        status = StatusLine(text="Ready | Press Ctrl+C to exit")
        
        return Box(
            children=[content, status]
        )


def main():
    """Run demo"""
    print("Starting zeroai-tui rich components demo...")
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
