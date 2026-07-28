"""
zeroai-tui: High-performance terminal UI framework
"""
__version__ = "0.3.0"

from .terminal import Terminal, Color, styled
from .renderer import get_renderer, Style
from .components import Component, Text, Box, Input, ScrollView
from .markdown import render_markdown, MarkdownRenderer
from .highlight import highlight_code, CodeHighlighter
from .rich_components import Markdown, CodeBlock, Panel, HorizontalLine, StatusLine
from .app import App, ChatApp
from .expert_selector import ExpertSelector
from .settings import SettingsDialog, SettingsScreen

__all__ = [
    # Terminal
    'Terminal',
    'Color',
    'styled',
    # Renderer
    'get_renderer',
    'Style',
    # Base components
    'Component',
    'Text',
    'Box',
    'Input',
    'ScrollView',
    # Rich components
    'Markdown',
    'CodeBlock',
    'Panel',
    'HorizontalLine',
    'StatusLine',
    # Utilities
    'render_markdown',
    'highlight_code',
    # Apps
    'App',
    'ChatApp',
    # New components
    'ExpertSelector',
    'SettingsDialog',
    'SettingsScreen',
]
