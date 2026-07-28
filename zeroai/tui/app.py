"""ZeroAI 主应用类

包装模块：从 tui_agent.py 重新导出 ZeroAI(App) 主类。
原实现保留在 tui_agent.py 中作为备份（约 2480 行，与 Textual 深度耦合）。

迁移来源：tui_agent.py 行 12269-14748

后续逐步解耦计划：
- 生命周期/CSS/绑定 → app.py 骨架
- 事件处理 → handlers.py
- 动作函数 → actions.py
当前阶段采用包装策略，确保项目稳定运行。
"""
from tui_agent import ZeroAI

__all__ = ["ZeroAI"]
