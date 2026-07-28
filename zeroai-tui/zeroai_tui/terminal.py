"""
zeroai-tui: Cross-platform terminal operations
"""
import sys
import os

# 优先使用包内 C 扩展（构建产物位于 zeroai_tui/_terminal.pyd）
# 旧逻辑用 sys.path 顶层导入 _terminal，会污染全局命名空间且与 setup.py
# 产生的包内扩展不匹配。这里改为包内相对导入，失败再回退纯 Python 实现。
try:
    from . import _terminal
except ImportError:
    # 开发环境下可能尚未构建，尝试把 src 目录加入 path 兼容旧脚本
    try:
        _src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
        if _src_dir not in sys.path:
            sys.path.insert(0, _src_dir)
        import _terminal  # type: ignore
    except ImportError:
        # Fallback to pure Python if C extension not built
        _terminal = None


class Terminal:
    """Cross-platform terminal operations"""
    
    @staticmethod
    def get_size() -> tuple:
        """Get terminal size (cols, rows)"""
        if _terminal:
            return _terminal.get_size()
        
        # Pure Python fallback
        try:
            cols, rows = os.get_terminal_size()
            return (cols, rows)
        except:
            return (80, 24)
    
    @staticmethod
    def set_raw_mode(enable: bool):
        """Enable/disable raw mode for keyboard input"""
        if _terminal:
            _terminal.set_raw_mode(1 if enable else 0)
            return
        
        # Pure Python fallback (limited)
        if sys.platform == 'win32':
            import msvcrt
            if enable:
                msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
            else:
                msvcrt.setmode(sys.stdin.fileno(), os.O_TEXT)
    
    @staticmethod
    def write(text: str):
        """Write string to terminal"""
        if _terminal:
            _terminal.write(text.encode('utf-8'))
            return
        
        # Pure Python fallback - use utf-8 encoding
        try:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            # Fallback: encode/decode with errors handling
            try:
                sys.stdout.buffer.write(text.encode('utf-8', errors='replace'))
                sys.stdout.buffer.flush()
            except Exception:
                pass
    
    @staticmethod
    def read_char() -> str:
        """Read single character"""
        if _terminal:
            result = _terminal.read_char()
            return result.decode('utf-8') if result else None
        
        # Pure Python fallback
        if sys.platform == 'win32':
            import msvcrt
            if msvcrt.kbhit():
                return msvcrt.getwch()
        else:
            import tty
            import termios
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
                return ch
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        
        return None
    
    @staticmethod
    def clear():
        """Clear terminal screen"""
        if _terminal:
            _terminal.clear()
            return
        
        # Pure Python fallback
        if sys.platform == 'win32':
            os.system('cls')
        else:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
    
    @staticmethod
    def move_cursor(row: int, col: int):
        """Move cursor to position"""
        if _terminal:
            _terminal.move_cursor(row, col)
            return
        
        # Pure Python fallback
        sys.stdout.write(f"\033[{row + 1};{col + 1}H")
        sys.stdout.flush()
    
    @staticmethod
    def set_cursor_visible(visible: bool):
        """Show/hide cursor"""
        if _terminal:
            _terminal.set_cursor_visible(1 if visible else 0)
            return
        
        # Pure Python fallback
        seq = "\033[?25h" if visible else "\033[?25l"
        sys.stdout.write(seq)
        sys.stdout.flush()
    
    @staticmethod
    def supports_color() -> bool:
        """Check if terminal supports ANSI colors"""
        if _terminal:
            return bool(_terminal.supports_color())
        
        # Pure Python fallback
        if os.environ.get('NO_COLOR'):
            return False
        
        if sys.platform == 'win32':
            # Windows 10+ supports ANSI
            return True
        
        term = os.environ.get('TERM', '')
        return 'color' in term or sys.stdout.isatty()


# ANSI color codes
class Color:
    """ANSI color codes"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    
    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"
    
    @staticmethod
    def rgb_fg(r: int, g: int, b: int) -> str:
        """Create RGB foreground color"""
        return f"\033[38;2;{r};{g};{b}m"
    
    @staticmethod
    def rgb_bg(r: int, g: int, b: int) -> str:
        """Create RGB background color"""
        return f"\033[48;2;{r};{g};{b}m"


def styled(text: str, *styles: str) -> str:
    """Apply styles to text"""
    if not Terminal.supports_color():
        return text
    
    prefix = "".join(styles)
    return f"{prefix}{text}{Color.RESET}"
