"""Markdown / LaTeX / 图片预览渲染（聚合入口）

本模块是 tui_agent.py 渲染函数的模块化聚合入口，提供以下能力：
- Markdown 渲染（基于 rich.markdown.Markdown）
- 学术 Markdown 规范化预处理
- LaTeX 公式 → Unicode 转换（含希腊字母、上下标、矩阵、cases 等）
- 图片预览（基于 PIL 半块字符渲染）
- LaTeX 在文本中的自动检测与渲染

设计原则（阶段 D.4）：
- 保留 tui_agent.py 中的原实现作为备份（不删除代码）
- 外部代码应通过 zeroai.tui.markdown 访问这些函数
- 后续可逐步迁移实现到本模块，但当前阶段仅做聚合导入

迁移来源：tui_agent.py 行 3602, 3626, 3679, 4249, 5243, 10332
"""
# 从 tui_agent.py 导入原实现（保留原代码不删除）
from tui_agent import (
    # Markdown 渲染
    render_markdown,
    _safe_markdown,
    _normalize_markdown_for_academic,
    # LaTeX 渲染
    render_latex_in_text,
    _latex_to_unicode,
    # 图片预览
    render_image_preview,
)

__all__ = [
    # Markdown 渲染
    "render_markdown",
    "_safe_markdown",
    "_normalize_markdown_for_academic",
    # LaTeX 渲染
    "render_latex_in_text",
    "_latex_to_unicode",
    # 图片预览
    "render_image_preview",
]


def is_loaded_from_tui_agent() -> bool:
    """检查当前模块是否从 tui_agent.py 加载实现

    用于诊断和迁移进度跟踪。返回 True 表示当前是包装模式，
    返回 False 表示实现已迁移到本模块。
    """
    import zeroai.tui.markdown as _self
    return _self.render_markdown.__module__ == "tui_agent"


def get_module_info() -> dict:
    """返回模块信息（用于自检和诊断）"""
    return {
        "mode": "wrapper" if is_loaded_from_tui_agent() else "standalone",
        "source": "tui_agent.py" if is_loaded_from_tui_agent() else "zeroai.tui.markdown",
        "exports": list(__all__),
        "count": len(__all__),
    }
