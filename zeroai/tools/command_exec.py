"""命令执行工具

迁移来源：tui_agent.py 行 1920-2141, 3263-3345

提供以下纯函数：
- _is_windows_local：判断本地操作系统是否为 Windows
- _translate_single_command：翻译单个命令（Linux ↔ Windows）
- _translate_command：翻译命令链（支持管道符）
- run_command：执行 shell 命令（全权限/受限模式）
- original_cmd_safe：对原始命令做简单脱敏
- exec_python：在受限环境中执行 Python 代码片段
- pip_install：包管理（安装/卸载/检查/列表）

依赖：
- zeroai.core.constants：PERMISSION_LEVEL
- 标准库：os, sys, re, locale, subprocess
"""
import os
import sys
import re
import locale
import subprocess

from zeroai.core.constants import PERMISSION_LEVEL


# 工作目录（受限模式下命令执行限制在此目录）
WORK_DIR = os.getcwd()


def _is_windows_local() -> bool:
    """检测本地操作系统是否为 Windows

    迁移来源：tui_agent.py 行 1919-1922
    """
    return sys.platform == "win32" or os.name == "nt"


# 跨平台命令映射表：Linux 命令 → Windows 等效命令
# 当用户在 Windows 上输入 Linux 命令时，自动转换为对应的 Windows 命令
_CROSS_PLATFORM_COMMAND_MAP = {
    # 列表/查看类
    "ls": "dir",
    "ll": "dir /Q",
    "la": "dir /A",
    "cat": "type",
    "less": "more",
    "head": "more",       # 简化映射，PowerShell 下可用 Select-Object -First
    "tail": "more",       # 简化映射
    "grep": "findstr",
    "find": "findstr",    # 注意：Windows 的 find 和 Linux 的 find 含义不同
    "which": "where",
    "whereis": "where",
    "echo": "echo",
    "pwd": "cd",
    "whoami": "whoami",
    "hostname": "hostname",
    "date": "date /t",
    "uptime": "net statistics workstation",
    "uname": "ver",
    "df": "wmic logicaldisk get name,size,freespace",
    "du": "dir /s",
    "free": "wmic OS get TotalVisibleMemorySize,FreePhysicalMemory",
    "top": "tasklist",
    "ps": "tasklist",
    "kill": "taskkill /PID",
    "killall": "taskkill /IM",
    # 网络
    "ifconfig": "ipconfig",
    "ip addr": "ipconfig",
    "netstat": "netstat -ano",
    "ss": "netstat -ano",
    "ping": "ping",
    "traceroute": "tracert",
    "tracepath": "tracert",
    "nslookup": "nslookup",
    "dig": "nslookup",
    "host": "nslookup",
    "curl": "curl",       # Windows 10+ 自带
    "wget": "curl -O",    # Windows 10+ 用 curl 替代
    # 服务
    "systemctl": "sc",    # 简化映射，实际语义不完全等价
    "service": "sc",
    # 文件操作
    "rm": "del",
    "rm -rf": "rmdir /s /q",
    "rmdir": "rmdir /s /q",
    "mkdir": "mkdir",
    "mv": "move",
    "cp": "copy",
    "touch": "type nul >",
    "chmod": "icacls",    # 权限管理
    "chown": "icacls",
    # 文本处理（近似映射）
    "sed": "powershell -Command (Get-Content).Replace()",
    "awk": "powershell -Command",
    "sort": "sort",
    "uniq": "sort /unique",
    "wc": "find /c /v \"\"",
    # 包管理
    "apt": "winget",
    "apt-get": "winget",
    "yum": "winget",
    "dnf": "winget",
    "pip": "pip",
    "python3": "python",
    # 其他
    "history": "doskey /history",
    "env": "set",
    "export": "set",
}


def _translate_single_command(cmd: str) -> tuple:
    """翻译单个命令（不含管道符）。返回 (translated, is_translated)。

    迁移来源：tui_agent.py 行 2000-2039
    """
    if not cmd or not cmd.strip():
        return cmd, False

    cmd = cmd.strip()
    parts = cmd.split(None, 1)
    if not parts:
        return cmd, False

    base_cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    cmd_lower = cmd.lower()

    # 优先检查：原命令是否已经是 Windows 格式（以某个 value 开头）
    # 避免 "netstat -ano" 被重复翻译为 "netstat -ano -ano"
    for win_cmd in _CROSS_PLATFORM_COMMAND_MAP.values():
        win_lower = win_cmd.lower()
        if cmd_lower == win_lower or cmd_lower.startswith(win_lower + " "):
            return cmd, False  # 已经是 Windows 命令，不翻译

    # 完整短语匹配优先（按 key 长度降序，确保 "rm -rf" 在 "rm" 之前匹配）
    for linux_cmd in sorted(_CROSS_PLATFORM_COMMAND_MAP.keys(), key=len, reverse=True):
        win_cmd = _CROSS_PLATFORM_COMMAND_MAP[linux_cmd]
        if cmd_lower == linux_cmd:
            return win_cmd, True
        if cmd_lower.startswith(linux_cmd + " "):
            # 去掉整个匹配短语作为 rest，保留剩余参数
            suffix = cmd[len(linux_cmd):].strip()
            translated = f"{win_cmd} {suffix}" if suffix else win_cmd
            return translated, True

    # 单词匹配（兜底）
    if base_cmd in _CROSS_PLATFORM_COMMAND_MAP:
        win_cmd = _CROSS_PLATFORM_COMMAND_MAP[base_cmd]
        if rest:
            return f"{win_cmd} {rest}", True
        return win_cmd, True

    return cmd, False


def _translate_command(command: str) -> tuple:
    """跨平台命令翻译：把 Linux 命令转换为 Windows 等效命令（或反之）。

    支持管道符组合命令翻译：对每个管道子命令单独翻译，再重新拼接。
    例如 'ls | grep x' → 'dir | findstr x'，'cat file | grep error' → 'type file | findstr error'。
    注意：保留 '||'（逻辑或）不分割，只按单个 '|' 分割。

    Returns:
        (translated_command, is_translated)
        - translated_command: 翻译后的命令（如无需翻译则返回原命令）
        - is_translated: 是否发生了翻译

    迁移来源：tui_agent.py 行 2042-2087
    """
    if not command or not command.strip():
        return command, False

    if not _is_windows_local():
        return command, False

    cmd = command.strip()

    # 按单个 | 分割（保留 || 不分割）
    # 正则：匹配单个 |，但其前后不是 |（负向后行/先行断言）
    # 先把 || 替换为占位符，避免被分割
    placeholder = "\x00OR\x00"
    cmd_protected = cmd.replace("||", placeholder)
    # 按单个 | 分割
    pipe_parts = cmd_protected.split("|")

    # 对每个子命令单独翻译
    translated_parts = []
    any_translated = False
    for part in pipe_parts:
        # 恢复 || 占位符
        part_restored = part.replace(placeholder, "||")
        sub_translated, sub_is = _translate_single_command(part_restored)
        if sub_is:
            any_translated = True
        translated_parts.append(sub_translated)

    if not any_translated:
        return command, False

    # 用 | 重新拼接（保留原 || 逻辑或）
    result = " | ".join(translated_parts)
    return result, True


def run_command(command: str, skip_translate: bool = False) -> str:
    """全权限模式：执行任意命令，无黑名单限制

    跨平台支持：自动识别 Linux 命令并转换为 Windows 等效命令（或反之）。
    例如在 Windows 上输入 'ls' 会自动转换为 'dir'，'cat file' 转换为 'type file'。

    Args:
        command: 要执行的命令
        skip_translate: 跳过跨平台翻译（语义化本地运维工具内部已适配，传 True 避免误翻译）

    迁移来源：tui_agent.py 行 2090-2133
    """
    # 危险命令黑名单（仅受限模式生效）
    dangerous = ["rm -rf /", "del /f /s /q C:\\", "format C:", "shutdown /s /t 0"]
    if PERMISSION_LEVEL != "full":
        if any(d in command.lower() for d in dangerous):
            return "已拦截危险命令（受限模式）"

    # 跨平台命令翻译（语义化工具已内部适配，跳过）
    original_command = command
    translate_hint = ""
    if not skip_translate:
        command, is_translated = _translate_command(command)
        if is_translated:
            translate_hint = f"[跨平台] 已将 '{original_cmd_safe(original_command)}' 翻译为 '{command}'\n"

    try:
        # 全权限：超时延长到 120 秒；受限：30 秒
        timeout = 120 if PERMISSION_LEVEL == "full" else 30
        # 全权限：cwd 限制放开（不强制 WORK_DIR）
        cwd = None if PERMISSION_LEVEL == "full" else WORK_DIR
        # encoding 使用本地默认（中文 Windows 为 GBK/cp936），errors='replace' 兜底
        # 避免某些命令（ipconfig/systeminfo/sc/netsh）输出非 UTF-8 时 UnicodeDecodeError
        r = subprocess.run(command, shell=True, capture_output=True,
                          text=True, timeout=timeout, cwd=cwd,
                          encoding=locale.getpreferredencoding(False),
                          errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        # 全权限：返回更长（8000）；受限：4000
        max_out = 8000 if PERMISSION_LEVEL == "full" else 4000
        result = out.strip()[:max_out] if out.strip() else "(无输出)"
        return translate_hint + result
    except subprocess.TimeoutExpired:
        return f"{translate_hint}错误：命令超时（>{timeout}秒）"
    except Exception as e:
        return f"{translate_hint}错误：{e}"


def original_cmd_safe(cmd: str) -> str:
    """对原始命令做简单脱敏（避免控制字符）

    迁移来源：tui_agent.py 行 2136-2138
    """
    return cmd[:200].replace("\n", " ").replace("\r", " ")


def exec_python(code: str, timeout: int = 10) -> str:
    """在受限环境中执行 Python 代码片段

    迁移来源：tui_agent.py 行 3263-3316
    """
    import io, sys
    # 危险模块黑名单 - 更严格的限制
    blocked = [
        "os.system", "os.popen", "subprocess", "eval", "exec", "compile",
        "__import__", "open(", "shutil.rmtree", "shutil.move",
        "ctypes", "windll", "cdll", "socket", "http", "urllib", "requests",
        "multiprocessing", "threading", "signal", "sys.exit", "sys.modules.pop",
        "importlib", "imp", "code", "codeop", "pdb", "bdb", "profile", "cProfile",
        "timeit", "unittest", "pytest", "doctest", "xmlrpc", "jsonrpc",
        "pickle", "shelve", "dbm", "sqlite3", "mysql", "psycopg2",
        "ftplib", "smtplib", "imaplib", "poplib", "telnetlib", "ssh", "paramiko",
        "numpy", "pandas", "matplotlib", "scipy", "PIL", "cv2", "opencv",
        "tensorflow", "torch", "keras", "django", "flask", "fastapi",
        "selenium", "playwright", "bs4", "lxml",
    ]
    for b in blocked:
        if b in code:
            return f"错误：代码包含受限操作 '{b}'"
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    captured = io.StringIO()
    sys.stdout = captured
    sys.stderr = captured
    # 限制可用内置函数
    safe_builtins = {
        k: v for k, v in __builtins__.items() if k not in (
            "exec", "eval", "compile", "__import__", "open", "input",
            "breakpoint", "exit", "quit"
        )
    } if isinstance(__builtins__, dict) else {}
    try:
        namespace = {"__builtins__": safe_builtins, "math": __import__("math"),
                     "json": __import__("json"), "re": __import__("re"),
                     "datetime": __import__("datetime"), "collections": __import__("collections")}
        exec(code, namespace)
        output = captured.getvalue()
        if not output:
            # 尝试返回最后一个表达式的值
            try:
                last_expr = code.strip().split("\n")[-1]
                if not last_expr.startswith(("import", "from", "def", "class", "for", "while", "if", "try", "with")):
                    result = eval(last_expr, namespace)
                    if result is not None:
                        output = str(result)
            except Exception:
                pass
        return output.strip() if output.strip() else "(无输出)"
    except Exception as e:
        return f"执行错误：{e}"
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def pip_install(package: str, action: str = "install") -> str:
    """包管理：安装/卸载/检查已安装/列表

    迁移来源：tui_agent.py 行 3319-3343
    """
    try:
        if action == "install":
            r = subprocess.run([sys.executable, "-m", "pip", "install", package, "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
                               capture_output=True, text=True, timeout=120)
            return r.stdout[-2000:] if r.returncode == 0 else f"安装失败：{r.stderr[-1000:]}"
        elif action == "uninstall":
            r = subprocess.run([sys.executable, "-m", "pip", "uninstall", package, "-y"],
                               capture_output=True, text=True, timeout=60)
            return r.stdout[-2000:] if r.returncode == 0 else f"卸载失败：{r.stderr[-1000:]}"
        elif action == "check":
            r = subprocess.run([sys.executable, "-m", "pip", "show", package],
                               capture_output=True, text=True, timeout=15)
            return r.stdout.strip() if r.returncode == 0 else f"未安装：{package}"
        elif action == "list":
            r = subprocess.run([sys.executable, "-m", "pip", "list", "--format=columns"],
                               capture_output=True, text=True, timeout=15)
            return r.stdout[:3000]
        else:
            return f"错误：未知操作 {action}，支持 install/uninstall/check/list"
    except subprocess.TimeoutExpired:
        return "错误：操作超时"
    except Exception as e:
        return f"错误：{e}"
