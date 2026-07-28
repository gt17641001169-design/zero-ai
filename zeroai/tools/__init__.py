"""Tool modules for ZeroAI

工具函数层模块集合，从 tui_agent.py 拆分而来。
每个模块独立可 import，不依赖 tui_agent.py。

模块清单：
- academic: 学术研究工具（文献搜索、引用校验、LaTeX 公式渲染）
- clipboard: 剪贴板操作（Windows API）
- command_exec: 命令执行（系统命令、Python 代码）
- doc_gen: 文档生成（Word/Excel/PDF）
- file_manager: 文件管理（读写、复制、移动、删除、编辑、diff、搜索）
- network: 网络操作（web 搜索、网页抓取、打开应用、git 状态）
- render: 渲染工具（Markdown、LaTeX）
- security: 安全扫描（代码漏洞、敏感信息、依赖漏洞）
- system_check: 系统检查（端口、进程、磁盘、防火墙、监控）
- window_mgr: 窗口管理（活动窗口、窗口列表、屏幕内容读取）
- voice: 语音交互（TTS 语音合成、ASR 语音识别）
- ssh_ops: SSH 远程运维（连接、执行、传输、部署、服务管理、健康体检）
- registry: 工具注册中心（聚合 TOOLS schema 和 TOOL_MAP，供上层调用）
"""
from zeroai.tools import (
    academic,
    clipboard,
    command_exec,
    doc_gen,
    file_manager,
    network,
    render,
    security,
    system_check,
    window_mgr,
    voice,
    ssh_ops,
    registry,
)

# 从 registry 重新导出 TOOLS / TOOL_MAP，便于上层一行导入：
#     from zeroai.tools import TOOLS, TOOL_MAP
from zeroai.tools.registry import TOOLS, TOOL_MAP

__all__ = [
    "academic",
    "clipboard",
    "command_exec",
    "doc_gen",
    "file_manager",
    "network",
    "render",
    "security",
    "system_check",
    "window_mgr",
    "voice",
    "ssh_ops",
    "registry",
    "TOOLS",
    "TOOL_MAP",
]
