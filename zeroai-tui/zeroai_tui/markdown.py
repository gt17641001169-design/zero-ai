"""
zeroai-tui: Markdown renderer
"""
import re
from typing import List, Tuple, Optional
from .renderer import Style
from .terminal import Color


class MarkdownRenderer:
    """Simple markdown renderer for terminal"""
    
    def __init__(self):
        # Color scheme
        self.colors = {
            'heading1': Color.BRIGHT_CYAN,
            'heading2': Color.CYAN,
            'heading3': Color.BRIGHT_GREEN,
            'bold': Color.BOLD,
            'italic': Color.ITALIC,
            'code': Color.BRIGHT_YELLOW,
            'code_block': Color.BRIGHT_GREEN,
            'link': Color.UNDERLINE + Color.CYAN,
            'bullet': Color.BRIGHT_WHITE,
            'number': Color.BRIGHT_WHITE,
            'quote': Color.DIM,
        }
    
    def render(self, text: str) -> List[Tuple[str, Style]]:
        """Render markdown to styled text lines"""
        lines = text.split('\n')
        result = []
        in_code_block = False
        code_block_lines = []
        code_block_lang = ""
        
        for line in lines:
            # Code block detection
            if line.strip().startswith('```'):
                if in_code_block:
                    # End code block
                    result.extend(self._render_code_block(code_block_lines, code_block_lang))
                    code_block_lines = []
                    code_block_lang = ""
                    in_code_block = False
                else:
                    # Start code block
                    in_code_block = True
                    code_block_lang = line.strip()[3:].strip()
                continue
            
            if in_code_block:
                code_block_lines.append(line)
                continue
            
            # Render line
            rendered = self._render_line(line)
            result.extend(rendered)
        
        # Handle unclosed code block
        if in_code_block and code_block_lines:
            result.extend(self._render_code_block(code_block_lines, code_block_lang))
        
        return result
    
    def _render_line(self, line: str) -> List[Tuple[str, Style]]:
        """Render a single line"""
        result = []
        
        # Empty line
        if not line.strip():
            result.append(('\n', Style()))
            return result
        
        # Headings
        if line.startswith('#'):
            level = len(line) - len(line.lstrip('#'))
            text = line.lstrip('#').strip()
            color = self.colors.get(f'heading{level}', self.colors['heading1'])
            result.append((f"{'━' * 40}\n", Style(fg=color)))
            result.append((f"{text}\n", Style(bold=True, fg=color)))
            result.append((f"{'━' * 40}\n", Style(fg=color)))
            return result
        
        # Horizontal rule
        if line.strip() in ('---', '***', '___'):
            result.append((f"{'━' * 40}\n", Style(fg=self.colors['quote'])))
            return result
        
        # Quote
        if line.startswith('>'):
            text = line[1:].strip()
            result.append((f"  │ {text}\n", Style(fg=self.colors['quote'], italic=True)))
            return result
        
        # Unordered list
        if re.match(r'^[\s]*[-*+]\s', line):
            indent = len(line) - len(line.lstrip())
            text = re.sub(r'^[\s]*[-*+]\s', '', line)
            rendered_text = self._render_inline(text)
            result.append(('  ' * (indent // 2) + '• ', Style(fg=self.colors['bullet'])))
            result.extend(rendered_text)
            result.append(('\n', Style()))
            return result
        
        # Ordered list
        if re.match(r'^[\s]*\d+\.\s', line):
            indent = len(line) - len(line.lstrip())
            match = re.match(r'^[\s]*(\d+)\.\s(.*)', line)
            if match:
                num = match.group(1)
                text = match.group(2)
                rendered_text = self._render_inline(text)
                result.append(('  ' * (indent // 2) + f'{num}. ', Style(fg=self.colors['number'])))
                result.extend(rendered_text)
                result.append(('\n', Style()))
                return result
        
        # Regular text with inline formatting
        rendered_text = self._render_inline(line)
        result.append(('  ', Style()))  # Indent
        result.extend(rendered_text)
        result.append(('\n', Style()))
        
        return result
    
    def _render_inline(self, text: str) -> List[Tuple[str, Style]]:
        """Render inline markdown (bold, italic, code, links)"""
        result = []
        i = 0
        
        while i < len(text):
            # Bold: **text** or __text__
            if text[i:i+2] in ('**', '__'):
                end = text.find(text[i:i+2], i + 2)
                if end != -1:
                    content = text[i+2:end]
                    result.append((content, Style(bold=True)))
                    i = end + 2
                    continue
            
            # Italic: *text* or _text_
            if text[i] == '*' and (i + 1 < len(text) and text[i+1] != '*'):
                end = text.find('*', i + 1)
                if end != -1 and end - i > 1:
                    content = text[i+1:end]
                    result.append((content, Style(italic=True)))
                    i = end + 1
                    continue
            
            # Inline code: `code`
            if text[i] == '`':
                end = text.find('`', i + 1)
                if end != -1:
                    content = text[i+1:end]
                    result.append((f' {content} ', Style(fg=self.colors['code'], bold=True)))
                    i = end + 1
                    continue
            
            # Link: [text](url)
            if text[i] == '[':
                match = re.match(r'\[([^\]]+)\]\([^)]+\)', text[i:])
                if match:
                    content = match.group(1)
                    result.append((content, Style(fg=self.colors['link'], underline=True)))
                    i += match.end()
                    continue
            
            # Plain text - collect until next special char
            j = i + 1
            while j < len(text) and text[j] not in ('*', '_', '`', '['):
                j += 1
            result.append((text[i:j], Style()))
            i = j
        
        return result
    
    def _render_code_block(self, lines: List[str], lang: str) -> List[Tuple[str, Style]]:
        """Render code block"""
        result = []
        
        # Header
        result.append((f"  ┌─ Code", Style(fg=self.colors['code_block'], bold=True)))
        if lang:
            result.append((f" ({lang})", Style(fg=self.colors['code_block'])))
        result.append(('\n', Style()))
        
        # Code lines with line numbers
        for i, line in enumerate(lines, 1):
            result.append((f"  │ {i:3d} │ ", Style(fg=self.colors['quote'])))
            result.append((f"{line}\n", Style(fg=self.colors['code_block'])))
        
        # Footer
        result.append((f"  └{'─' * 38}\n", Style(fg=self.colors['code_block'])))
        
        return result


# Global renderer instance
_md_renderer: Optional[MarkdownRenderer] = None


def get_md_renderer() -> MarkdownRenderer:
    """Get global markdown renderer"""
    global _md_renderer
    if _md_renderer is None:
        _md_renderer = MarkdownRenderer()
    return _md_renderer


def render_markdown(text: str) -> List[Tuple[str, Style]]:
    """Render markdown text to styled lines"""
    return get_md_renderer().render(text)
