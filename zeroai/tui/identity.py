"""身份泄露过滤

包装模块：从 tui_agent.py / zeroai.core.response_utils 重新导出。
原实现保留在 tui_agent.py 中作为备份。

迁移来源：tui_agent.py 行 10120-10154
"""
# 优先使用 zeroai.core 中的实现（阶段3 已切换）
try:
    from zeroai.core.response_utils import _sanitize_identity_leak
except ImportError:
    from tui_agent import _sanitize_identity_leak

# 模式常量和替换文本仍从 tui_agent.py 导入（core 未导出常量）
from tui_agent import _IDENTITY_LEAK_PATTERNS, _IDENTITY_REPLACEMENT

__all__ = [
    "_IDENTITY_LEAK_PATTERNS",
    "_IDENTITY_REPLACEMENT",
    "_sanitize_identity_leak",
]
