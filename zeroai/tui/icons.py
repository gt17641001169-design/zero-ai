"""ZeroAI TUI 图标加载工具

从 tui_agent.py 行251-269 迁移。
终端环境无法渲染 SVG，返回文字标签替代。
"""
from pathlib import Path
import sys
import os

# 图标标签映射（终端用文字标签替代 SVG 图标）
ICON_LABELS = {
    "folder": "[DIR]",
    "file": "[FILE]",
    "search": "[SCAN]",
    "check": "[OK]",
    "cross": "[ERR]",
    "warning": "[!]",
    "security": "[SEC]",
    "monitor": "[SCREEN]",
    "download": "[DL]",
    "document": "[DOC]",
    "tool": "[TOOL]",
}


def _get_icons_dir() -> Path:
    """获取图标目录路径"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后
        return Path(sys._MEIPASS) / "assets" / "icons"
    else:
        # 源码运行：项目根目录/assets/icons
        # 尝试多个位置
        candidates = [
            Path(__file__).parent.parent.parent / "assets" / "icons",  # d:\C\C\assets\icons
            Path(__file__).parent.parent / "assets" / "icons",          # zeroai/assets/icons
        ]
        for p in candidates:
            if p.exists():
                return p
        return candidates[0]


def _load_svg_icon(name: str) -> str:
    """加载 SVG 图标文件内容，返回纯文本标签（终端无法渲染 SVG，返回文字标签）

    从 tui_agent.py 行251-269 迁移。
    """
    icons_dir = _get_icons_dir()
    svg_path = icons_dir / f"{name}.svg"
    if svg_path.exists():
        return ICON_LABELS.get(name, "")
    return ""
