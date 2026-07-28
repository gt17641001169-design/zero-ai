"""
zeroai-tui: Code syntax highlighter
"""
import re
from typing import List, Tuple, Optional
from .renderer import Style
from .terminal import Color


class CodeHighlighter:
    """Simple syntax highlighter for code"""
    
    # Language keywords
    KEYWORDS = {
        'python': ['def', 'class', 'if', 'else', 'elif', 'for', 'while', 'return', 
                   'import', 'from', 'as', 'try', 'except', 'finally', 'with', 'lambda',
                   'and', 'or', 'not', 'in', 'is', 'True', 'False', 'None', 'print'],
        'javascript': ['function', 'const', 'let', 'var', 'if', 'else', 'for', 'while',
                       'return', 'import', 'export', 'class', 'new', 'this', 'async',
                       'await', 'try', 'catch', 'finally', 'null', 'undefined', 'true', 'false'],
        'rust': ['fn', 'let', 'mut', 'if', 'else', 'for', 'while', 'loop', 'return',
                 'struct', 'enum', 'impl', 'trait', 'pub', 'use', 'mod', 'self', 'super',
                 'true', 'false', 'Some', 'None', 'Ok', 'Err'],
        'go': ['func', 'var', 'const', 'if', 'else', 'for', 'range', 'return', 'package',
               'import', 'struct', 'interface', 'map', 'chan', 'go', 'defer', 'select',
               'true', 'false', 'nil'],
    }
    
    def __init__(self):
        self.colors = {
            'keyword': Color.BRIGHT_MAGENTA,
            'string': Color.BRIGHT_GREEN,
            'number': Color.BRIGHT_CYAN,
            'comment': Color.DIM,
            'function': Color.BRIGHT_YELLOW,
            'type': Color.BRIGHT_BLUE,
            'operator': Color.BRIGHT_WHITE,
            'punctuation': Color.BRIGHT_WHITE,
            'decorator': Color.BRIGHT_YELLOW,
        }
    
    def highlight(self, code: str, language: str = '') -> List[Tuple[str, Style]]:
        """Highlight code and return styled text"""
        if not language:
            language = self._detect_language(code)
        
        lines = code.split('\n')
        result = []
        
        for line in lines:
            highlighted = self._highlight_line(line, language)
            result.extend(highlighted)
            result.append(('\n', Style()))
        
        return result
    
    def _detect_language(self, code: str) -> str:
        """Auto-detect programming language"""
        # Python detection
        if re.search(r'def\s+\w+\s*\(', code) or 'import ' in code or 'print(' in code:
            return 'python'
        # JavaScript detection
        if re.search(r'function\s+\w+', code) or '=>' in code or 'console.log' in code:
            return 'javascript'
        # Rust detection
        if re.search(r'fn\s+\w+', code) or 'let mut' in code or 'impl ' in code:
            return 'rust'
        # Go detection
        if 'func ' in code or 'package ' in code:
            return 'go'
        return ''
    
    def _highlight_line(self, line: str, language: str) -> List[Tuple[str, Style]]:
        """Highlight a single line"""
        result = []
        i = 0
        
        while i < len(line):
            # Comment detection
            if line[i:i+2] == '//' or line[i:i+2] == '#':
                result.append((line[i:], Style(fg=self.colors['comment'])))
                return result
            
            # String detection (double or single quotes)
            if line[i] in ('"', "'"):
                quote = line[i]
                # Check for triple quotes
                if line[i:i+3] in ('"""', "'''"):
                    quote = line[i:i+3]
                end = line.find(quote, i + len(quote))
                if end != -1:
                    end += len(quote)
                    result.append((line[i:end], Style(fg=self.colors['string'])))
                    i = end
                    continue
                else:
                    result.append((line[i:], Style(fg=self.colors['string'])))
                    return result
            
            # Decorator detection
            if line[i] == '@':
                end = line.find(' ', i)
                if end == -1:
                    end = len(line)
                result.append((line[i:end], Style(fg=self.colors['decorator'])))
                i = end
                continue
            
            # Number detection
            if line[i].isdigit():
                j = i + 1
                while j < len(line) and (line[j].isdigit() or line[j] in '.'):
                    j += 1
                result.append((line[i:j], Style(fg=self.colors['number'])))
                i = j
                continue
            
            # Keyword detection
            keywords = self.KEYWORDS.get(language, [])
            for kw in keywords:
                if line[i:i+len(kw)] == kw and (i + len(kw) >= len(line) or not line[i+len(kw)].isalnum()):
                    # Check if it's a function call
                    rest = line[i+len(kw):].lstrip()
                    if rest.startswith('('):
                        result.append((kw, Style(fg=self.colors['function'])))
                    else:
                        result.append((kw, Style(fg=self.colors['keyword'])))
                    i += len(kw)
                    break
            else:
                # Regular character
                j = i + 1
                while j < len(line) and line[j] not in ('"', "'", '#', '@', ' '):
                    j += 1
                result.append((line[i:j], Style()))
                i = j
        
        return result
    
    def _is_function_call(self, line: str, pos: int) -> bool:
        """Check if identifier at position is a function call"""
        # Find end of identifier
        j = pos
        while j < len(line) and (line[j].isalnum() or line[j] == '_'):
            j += 1
        
        # Check if followed by parenthesis
        rest = line[j:].lstrip()
        return rest.startswith('(')


# Global highlighter instance
_code_highlighter: Optional[CodeHighlighter] = None


def get_code_highlighter() -> CodeHighlighter:
    """Get global code highlighter"""
    global _code_highlighter
    if _code_highlighter is None:
        _code_highlighter = CodeHighlighter()
    return _code_highlighter


def highlight_code(code: str, language: str = '') -> List[Tuple[str, Style]]:
    """Highlight code and return styled text"""
    return get_code_highlighter().highlight(code, language)
