"""
zeroai-tui: Rendering engine with C/Zig acceleration

渲染调用链（严格按你的架构图）：
    Python (renderer.py)
        ↓ 仅通过 _renderer C 扩展入口
    C     (_renderer.c)
        ↓ 内部 LoadLibrary/dlopen 动态加载
    Zig   (zig_render.dll / libzig_render.so)
        ↓ 失败自动回退
    C     (_renderer.c 标量实现)
        ↓ C 扩展也不存在时
    Python (本文件内的纯 Python 实现)

注意：不再直接走 _zig_bindings.py，Zig 加载逻辑完全在 C 层内部完成。
      _zig_bindings.py 保留作为独立调试工具，不参与生产渲染路径。
"""
from typing import List, Optional, Tuple
from .terminal import Terminal, Color, styled

# C 扩展是唯一入口（内部自动尝试 Zig 加速，失败回退到 C 标量实现）
try:
    from . import _renderer
    HAS_C_RENDERER = True
except ImportError:
    HAS_C_RENDERER = False

# Zig 可用性查询（通过 C 扩展的 zig_available 方法，不直接导入 _zig_bindings）
def _query_zig_available() -> bool:
    """查询 Zig 加速是否可用（通过 C 扩展查询）"""
    if not HAS_C_RENDERER:
        return False
    try:
        return bool(_renderer.zig_available())
    except Exception:
        return False

HAS_ZIG_RENDERER = _query_zig_available()


class Style:
    """Text style"""
    def __init__(self, 
                 bold: bool = False,
                 dim: bool = False,
                 italic: bool = False,
                 underline: bool = False,
                 fg: Optional[str] = None,
                 bg: Optional[str] = None):
        self.bold = bold
        self.dim = dim
        self.italic = italic
        self.underline = underline
        self.fg = fg
        self.bg = bg
    
    def apply(self, text: str) -> str:
        """Apply style to text"""
        if not Terminal.supports_color():
            return text
        
        codes = []
        if self.bold:
            codes.append(Color.BOLD)
        if self.dim:
            codes.append(Color.DIM)
        if self.italic:
            codes.append(Color.ITALIC)
        if self.underline:
            codes.append(Color.UNDERLINE)
        if self.fg:
            codes.append(self.fg)
        if self.bg:
            codes.append(self.bg)
        
        if not codes:
            return text
        
        prefix = "".join(codes)
        return f"{prefix}{text}{Color.RESET}"


class RenderBuffer:
    """Off-screen render buffer"""
    
    def __init__(self, cols: int, rows: int):
        self.cols = cols
        self.rows = rows
        self.buffer: List[List[str]] = [[' ' for _ in range(cols)] for _ in range(rows)]
        self.styles: List[List[Optional[Style]]] = [[None for _ in range(cols)] for _ in range(rows)]
    
    def put(self, row: int, col: int, char: str, style: Optional[Style] = None):
        """Put character at position"""
        if 0 <= row < self.rows and 0 <= col < self.cols:
            self.buffer[row][col] = char
            self.styles[row][col] = style
    
    def write(self, row: int, col: int, text: str, style: Optional[Style] = None):
        """Write string at position"""
        for i, char in enumerate(text):
            self.put(row, col + i, char, style)
    
    def clear(self):
        """Clear buffer"""
        self.buffer = [[' ' for _ in range(self.cols)] for _ in range(self.rows)]
        self.styles = [[None for _ in range(self.cols)] for _ in range(self.rows)]
    
    def render(self) -> str:
        """Render buffer to ANSI string"""
        lines = []
        for row in range(self.rows):
            line_parts = []
            current_style = None
            
            for col in range(self.cols):
                char = self.buffer[row][col]
                style = self.styles[row][col]
                
                # Only add style change when needed
                if style != current_style:
                    if style:
                        line_parts.append(style.apply(char))
                    else:
                        if current_style:
                            line_parts.append(Color.RESET)
                        line_parts.append(char)
                    current_style = style
                else:
                    line_parts.append(char)
            
            if current_style:
                line_parts.append(Color.RESET)
            
            lines.append("".join(line_parts))
        
        return "\n".join(lines)


class Renderer:
    """Terminal renderer with double buffering"""
    
    def __init__(self):
        self.cols, self.rows = Terminal.get_size()
        self.current_buffer = RenderBuffer(self.cols, self.rows)
        self.next_buffer = RenderBuffer(self.cols, self.rows)
        self._last_render = ""
    
    def resize(self):
        """Handle terminal resize"""
        self.cols, self.rows = Terminal.get_size()
        self.current_buffer = RenderBuffer(self.cols, self.rows)
        self.next_buffer = RenderBuffer(self.cols, self.rows)
    
    def clear(self):
        """Clear next buffer"""
        self.next_buffer.clear()
    
    def put(self, row: int, col: int, char: str, style: Optional[Style] = None):
        """Put character in next buffer"""
        self.next_buffer.put(row, col, char, style)
    
    def write(self, row: int, col: int, text: str, style: Optional[Style] = None):
        """Write string in next buffer"""
        self.next_buffer.write(row, col, text, style)
    
    def flush(self):
        """Flush next buffer to terminal"""
        # C 扩展是唯一入口，内部自动尝试 Zig 加速，失败回退到 C 标量实现
        if HAS_C_RENDERER:
            try:
                output = _renderer.diff_buffers(
                    self.current_buffer.buffer,
                    self.current_buffer.styles,
                    self.next_buffer.buffer,
                    self.next_buffer.styles,
                    self.rows,
                    self.cols
                )

                # Swap buffers
                self.current_buffer, self.next_buffer = self.next_buffer, self.current_buffer

                # Write to terminal
                if output:
                    Terminal.write(output)
                return
            except Exception:
                # Fall back to Python implementation
                pass

        # Python fallback（C 扩展不可用时）
        output = []
        last_style = None

        for row in range(self.rows):
            for col in range(self.cols):
                char = self.next_buffer.buffer[row][col]
                style = self.next_buffer.styles[row][col]

                # Skip unchanged characters (optimization)
                if (self.current_buffer.buffer[row][col] == char and
                    self.current_buffer.styles[row][col] == style):
                    continue

                # Move cursor if needed
                output.append(f"\033[{row + 1};{col + 1}H")

                # Apply style
                if style != last_style:
                    if style:
                        codes = []
                        if style.bold:
                            codes.append(Color.BOLD)
                        if style.dim:
                            codes.append(Color.DIM)
                        if style.fg:
                            codes.append(style.fg)
                        if style.bg:
                            codes.append(style.bg)
                        output.append("".join(codes))
                    else:
                        output.append(Color.RESET)
                    last_style = style

                output.append(char)

        output.append(Color.RESET)

        # Swap buffers
        self.current_buffer, self.next_buffer = self.next_buffer, self.current_buffer

        # Write to terminal
        if output:
            Terminal.write("".join(output))

    def zig_available(self) -> bool:
        """查询 Zig 加速是否可用（通过 C 扩展查询）"""
        if not HAS_C_RENDERER:
            return False
        try:
            return bool(_renderer.zig_available())
        except Exception:
            return False

    def reload_zig(self) -> bool:
        """强制重新加载 Zig 库（开发期 zig build 后热加载）

        Returns:
            True 表示重新加载后 Zig 可用
        """
        if not HAS_C_RENDERER:
            return False
        try:
            result = bool(_renderer.reload_zig())
            # 更新模块级全局变量
            global HAS_ZIG_RENDERER
            HAS_ZIG_RENDERER = result
            return result
        except Exception:
            return False


# Global renderer instance
_renderer: Optional[Renderer] = None


def get_renderer() -> Renderer:
    """Get global renderer instance"""
    global _renderer
    if _renderer is None:
        _renderer = Renderer()
    return _renderer
