"""Markdown / LaTeX / 图片预览渲染

包装模块：从 tui_agent.py 重新导出，提供模块化访问路径。
原实现保留在 tui_agent.py 中作为备份，本模块仅做聚合导入。

迁移来源：tui_agent.py 行 3444, 3523, 5085, 10157
"""
# 从 tui_agent.py 导入原实现（保留原代码不删除）
from tui_agent import (
    render_markdown,
    _safe_markdown,
    render_latex_in_text,
    render_image_preview,
)

__all__ = [
    "render_markdown",
    "_safe_markdown",
    "render_latex_in_text",
    "render_image_preview",
]
