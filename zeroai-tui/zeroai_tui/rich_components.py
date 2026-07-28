"""
zeroai-tui: Rich components (Markdown, CodeBlock, Panel)
"""
from typing import List, Optional
from .components import Component, Text
from .renderer import get_renderer, Style
from .terminal import Color
from .markdown import render_markdown
from .highlight import highlight_code


class Markdown(Component):
    """Markdown display component"""
    
    def __init__(self, content: str = "", id: Optional[str] = None):
        super().__init__(id)
        self.content = content
        self._rendered_lines = []
        self._update_rendered()
    
    def _update_rendered(self):
        """Update rendered markdown lines"""
        self._rendered_lines = render_markdown(self.content)
    
    def set_content(self, content: str):
        """Update markdown content"""
        self.content = content
        self._update_rendered()
        self.mark_dirty()
    
    def render(self):
        """Render markdown component"""
        if not self.visible:
            return

        renderer = get_renderer()
        row, col, width, height = self.y, self.x, self.width, self.height

        current_row = row
        for styled_text, style in self._rendered_lines:
            if current_row >= row + height:
                break

            # Handle newlines
            lines = styled_text.split('\n')
            for line in lines:
                if current_row >= row + height:
                    break

                # Truncate if too long
                display_line = line[:width] if len(line) > width else line
                renderer.write(current_row, col, display_line, style)
                current_row += 1


class CodeBlock(Component):
    """Code block with syntax highlighting"""
    
    def __init__(self, code: str = "", language: str = "", id: Optional[str] = None):
        super().__init__(id)
        self.code = code
        self.language = language
        self._rendered_lines = []
        self._update_rendered()
    
    def _update_rendered(self):
        """Update rendered code lines"""
        # Add header
        self._rendered_lines = [
            (f"┌─ Code", Style(fg=Color.BRIGHT_GREEN, bold=True)),
            (f" ({self.language})" if self.language else "", Style(fg=Color.BRIGHT_GREEN)),
            ("\n", Style()),
        ]
        
        # Highlight code
        highlighted = highlight_code(self.code, self.language)
        self._rendered_lines.extend(highlighted)
        
        # Add footer
        self._rendered_lines.append((f"└{'─' * 38}\n", Style(fg=Color.BRIGHT_GREEN)))
    
    def set_code(self, code: str, language: str = ""):
        """Update code content"""
        self.code = code
        self.language = language
        self._update_rendered()
        self.mark_dirty()
    
    def render(self):
        """Render code block"""
        if not self.visible:
            return

        renderer = get_renderer()
        row, col, width, height = self.y, self.x, self.width, self.height

        current_row = row
        for styled_text, style in self._rendered_lines:
            if current_row >= row + height:
                break

            # Handle newlines
            lines = styled_text.split('\n')
            for line in lines:
                if current_row >= row + height:
                    break

                # Truncate if too long
                display_line = line[:width] if len(line) > width else line
                renderer.write(current_row, col, display_line, style)
                current_row += 1


class Panel(Component):
    """Panel with border"""
    
    def __init__(self, 
                 child: Optional[Component] = None,
                 title: str = "",
                 border_style: Optional[Style] = None,
                 id: Optional[str] = None):
        super().__init__(id)
        self.child = child
        self.title = title
        self.border_style = border_style or Style(fg=Color.WHITE)
        
        if child:
            child.parent = self
    
    def set_child(self, child: Component):
        """Set child component"""
        if self.child:
            self.child.parent = None
        self.child = child
        child.parent = self
        self.mark_dirty()
    
    def render(self):
        """Render panel with border"""
        if not self.visible:
            return

        renderer = get_renderer()
        row, col, width, height = self.y, self.x, self.width, self.height

        if width < 2 or height < 2:
            return

        # Draw border
        # Top
        if self.title:
            title_text = f" {self.title} "
            title_len = len(title_text)
            border_len = width - 2
            left_len = (border_len - title_len) // 2
            right_len = border_len - left_len - title_len

            renderer.write(row, col, "┌", self.border_style)
            renderer.write(row, col + 1, "─" * left_len, self.border_style)
            renderer.write(row, col + 1 + left_len, title_text, Style(bold=True))
            renderer.write(row, col + 1 + left_len + title_len, "─" * right_len, self.border_style)
            renderer.write(row, col + width - 1, "┐", self.border_style)
        else:
            renderer.write(row, col, "┌" + "─" * (width - 2) + "┐", self.border_style)

        # Sides
        for i in range(1, height - 1):
            renderer.put(row + i, col, "│", self.border_style)
            renderer.put(row + i, col + width - 1, "│", self.border_style)

        # Bottom
        renderer.write(row + height - 1, col, "└" + "─" * (width - 2) + "┘", self.border_style)

        # Render child (layout child inside panel)
        if self.child:
            self.child.set_geometry(col + 1, row + 1, width - 2, height - 2)
            self.child.render()


class HorizontalLine(Component):
    """Horizontal line separator"""
    
    def __init__(self, style: Optional[Style] = None, id: Optional[str] = None):
        super().__init__(id)
        self.style = style or Style(fg=Color.WHITE)
    
    def render(self):
        """Render horizontal line"""
        if not self.visible:
            return

        renderer = get_renderer()
        renderer.write(self.y, self.x, "─" * self.width, self.style)


class StatusLine(Component):
    """Status line at bottom"""
    
    def __init__(self, text: str = "", style: Optional[Style] = None, id: Optional[str] = None):
        super().__init__(id)
        self.text = text
        self.style = style or Style(bold=True, fg=Color.WHITE)
    
    def set_text(self, text: str):
        """Update status text"""
        self.text = text
        self.mark_dirty()
    
    def render(self):
        """Render status line"""
        if not self.visible:
            return

        renderer = get_renderer()
        row, col, width = self.y, self.x, self.width

        # Background bar
        renderer.write(row, col, " " * width, Style(fg=Color.BLACK, bg=Color.WHITE))

        # Text
        display_text = self.text[:width-2] if len(self.text) > width-2 else self.text
        renderer.write(row, col + 1, display_text, self.style)
