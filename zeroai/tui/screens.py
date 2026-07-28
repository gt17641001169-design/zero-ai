"""TUI 模态对话框

包装模块：从 tui_agent.py 重新导出 Textual 模态屏。
原实现保留在 tui_agent.py 中作为备份。

迁移来源：tui_agent.py 行 10367-12267
- AddModelScreen: 添加自定义模型对话框
- SettingsScreen: 设置面板
- VoiceDialogScreen: 语音对话对话框
"""
from tui_agent import (
    AddModelScreen,
    SettingsScreen,
    VoiceDialogScreen,
)

__all__ = [
    "AddModelScreen",
    "SettingsScreen",
    "VoiceDialogScreen",
]
