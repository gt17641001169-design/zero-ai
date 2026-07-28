"""TUI 自定义组件

包装模块：从 tui_agent.py 重新导出 Textual 自定义组件。
原实现保留在 tui_agent.py 中作为备份。

迁移来源：tui_agent.py 行 10170-10366
- InfoBar: 顶部信息栏（极简灰色）
- HintBar: 底部快捷键栏
- TokenBar: 右侧 token 使用栏
"""
from tui_agent import (
    InfoBar,
    HintBar,
    TokenBar,
)

__all__ = [
    "InfoBar",
    "HintBar",
    "TokenBar",
]
