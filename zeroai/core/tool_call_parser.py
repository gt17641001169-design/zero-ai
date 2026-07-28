"""工具调用 XML 解析器（独立模块）

本模块从 tui_agent.py 的 _parse_tool_call_xml / _split_csv_args 抽取而来，
作为 zeroai.core 的独立组件，便于：
1. 单元测试（不依赖 tui_agent.py 的全局状态）
2. 复用（MCP Server / Agent Loop 可直接调用）
3. 未来切换：tui_agent.py 可通过切换块优先使用本模块

解析的两种格式：
1. JSON 格式：{"name": "...", "arguments": {...}}
2. 函数调用格式：name(key=value, key2="str,with,comma")

源文件：tui_agent.py 行 1087-1175
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List


__all__ = [
    "parse_tool_call_xml",
    "split_csv_args",
    "needs_tool_calls",
]


# ============================================================================
# 工具调用关键词（用于判断是否需要工具调用）
# 迁移来源：tui_agent.py 行 1056-1084
# ============================================================================
_TOOL_KEYWORDS = [
    # 命令执行
    "运行", "执行", "命令", "cmd", "powershell", "shell", "bash", "terminal",
    # 文件/代码操作
    "文件", "读取", "写入", "修改", "创建", "删除", "搜索", "查找", "代码", "项目", "仓库",
    "read_file", "write_file", "edit_file", "search_files", "list_dir",
    # 网络/应用
    "网络", "网速", "ping", "ip", "域名", "网站", "搜索", "打开", "浏览器", "应用",
    # SSH/运维
    "ssh", "远程", "部署", "docker", "容器", "防火墙", "服务", "进程",
    # 安全/文档/学术
    "审计", "漏洞", "安全", "生成文档", "word", "excel", "pdf", "论文", "文献", "arxiv",
    # 窗口/语音
    "窗口", "截图", "剪贴板", "语音", "朗读", "录音",
]


def needs_tool_calls(text: str) -> bool:
    """判断文本是否暗示需要工具调用（用于路由决策）

    迁移来源：tui_agent.py 行 1056-1084

    Args:
        text: 用户输入文本

    Returns:
        True 表示文本包含工具调用关键词
    """
    if not text:
        return False
    return any(kw in text for kw in _TOOL_KEYWORDS)


# ============================================================================
# CSV 参数拆分（尊重引号）
# 迁移来源：tui_agent.py 行 1087-1109
# ============================================================================
def split_csv_args(s: str) -> List[str]:
    """拆分函数调用参数字符串，尊重引号内的逗号。

    用于解析 <tool_call>name(a="1,2", b=3)</tool_call> 中的参数。

    Args:
        s: 参数字符串，如 'a="1,2", b=3'

    Returns:
        拆分后的参数列表，如 ['a="1,2"', 'b=3']
    """
    parts: List[str] = []
    current = ""
    in_quote = None
    for ch in s:
        if ch in ('"', "'"):
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
            current += ch
        elif ch == "," and in_quote is None:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


# ============================================================================
# 工具调用 XML 解析
# 迁移来源：tui_agent.py 行 1112-1175
# ============================================================================
_TOOL_CALL_PATTERN = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_FUNC_CALL_PATTERN = re.compile(r"(\w+)\s*\((.*)\)\s*$", re.DOTALL)


def parse_tool_call_xml(text: str) -> List[Dict[str, Any]]:
    """解析模型输出的 <tool_call>...</tool_call> 伪 XML 工具调用。

    某些模型（如 GLM-4.7-Flash）即使提供了 tools 参数，仍会输出文本形式的
    <tool_call>name(args)</tool_call> 而不是标准的 delta.tool_calls。
    本函数做兜底解析，返回 [{"name": "...", "arguments": "json-string"}, ...]。

    支持两种格式：
    1. JSON 格式：<tool_call>{"name": "read_file", "arguments": {"path": "/tmp"}}</tool_call>
    2. 函数调用格式：<tool_call>read_file(path="/tmp", offset=0)</tool_call>

    Args:
        text: 模型输出文本

    Returns:
        工具调用列表，每个元素为 {"name": str, "arguments": str(JSON)}
    """
    if not text:
        return []

    calls: List[Dict[str, Any]] = []

    for match in _TOOL_CALL_PATTERN.finditer(text):
        inner = match.group(1).strip()
        call: Dict[str, Any] = {"name": "", "arguments": "{}"}

        # 1) 尝试 JSON 格式：{"name": "...", "arguments": {...}}
        try:
            data = json.loads(inner)
            if isinstance(data, dict):
                call["name"] = data.get("name", data.get("function", {}).get("name", ""))
                args = data.get("arguments", data.get("function", {}).get("arguments", {}))
                if isinstance(args, dict):
                    call["arguments"] = json.dumps(args, ensure_ascii=False)
                else:
                    call["arguments"] = str(args)
                if call["name"]:
                    calls.append(call)
                continue
        except Exception:
            pass

        # 2) 尝试 name(args) 或 name(key=value, ...) 格式
        m = _FUNC_CALL_PATTERN.match(inner)
        if m:
            name, args_str = m.group(1), m.group(2).strip()
            call["name"] = name
            args: Dict[str, Any] = {}
            if args_str:
                for part in split_csv_args(args_str):
                    if "=" not in part:
                        continue
                    k, v = part.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    # 去除字符串引号
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    else:
                        # 尝试解析数字 / bool / null
                        try:
                            if "." in v:
                                v = float(v)
                            else:
                                v = int(v)
                        except ValueError:
                            lv = v.lower()
                            if lv == "true":
                                v = True
                            elif lv == "false":
                                v = False
                            elif lv in ("none", "null"):
                                v = None
                    args[k] = v
            call["arguments"] = json.dumps(args, ensure_ascii=False)
            calls.append(call)

    return calls


# ============================================================================
# 自检
# ============================================================================
def self_test() -> bool:
    """快速自检：验证解析逻辑正确

    Returns:
        True 表示自检通过
    """
    # 测试 1：JSON 格式
    text1 = '<tool_call>{"name": "read_file", "arguments": {"path": "/tmp/test"}}</tool_call>'
    calls1 = parse_tool_call_xml(text1)
    if len(calls1) != 1:
        return False
    if calls1[0]["name"] != "read_file":
        return False
    if '"path": "/tmp/test"' not in calls1[0]["arguments"]:
        return False

    # 测试 2：函数调用格式
    text2 = '<tool_call>write_file(path="/tmp/a", content="hello,world")</tool_call>'
    calls2 = parse_tool_call_xml(text2)
    if len(calls2) != 1:
        return False
    if calls2[0]["name"] != "write_file":
        return False
    # 验证引号内的逗号不被拆分
    if '"hello,world"' not in calls2[0]["arguments"]:
        return False

    # 测试 3：多个工具调用
    text3 = '<tool_call>read_file(path="/a")</tool_call><tool_call>list_dir(path="/b")</tool_call>'
    calls3 = parse_tool_call_xml(text3)
    if len(calls3) != 2:
        return False

    # 测试 4：空文本
    if parse_tool_call_xml("") != []:
        return False

    # 测试 5：无 tool_call 标签
    if parse_tool_call_xml("普通文本") != []:
        return False

    # 测试 6：数字/bool/null 解析
    text6 = '<tool_call>test(int_val=42, float_val=3.14, bool_true=true, bool_false=false, null_val=null)</tool_call>'
    calls6 = parse_tool_call_xml(text6)
    if len(calls6) != 1:
        return False
    import json as _json
    args6 = _json.loads(calls6[0]["arguments"])
    if args6.get("int_val") != 42:
        return False
    if args6.get("float_val") != 3.14:
        return False
    if args6.get("bool_true") is not True:
        return False
    if args6.get("bool_false") is not False:
        return False
    if args6.get("null_val") is not None:
        return False

    # 测试 7：needs_tool_calls
    if not needs_tool_calls("帮我读取文件"):
        return False
    if needs_tool_calls("你好"):
        return False

    return True


if __name__ == "__main__":
    print(f"Self-test: {'PASS' if self_test() else 'FAIL'}")
