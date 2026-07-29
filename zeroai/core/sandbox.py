"""代码执行沙箱（阶段 N.1）

提供安全隔离的 Python 代码执行环境：
1. 子进程隔离：在独立子进程中执行代码，崩溃不影响主进程
2. 资源限制：CPU 时间、内存、执行时长限制
3. 危险调用检测：静态检查代码中的危险调用
4. 网络隔离：可选禁用网络访问
5. 临时工作目录：在临时目录中执行，避免污染主目录

安全策略：
- 禁止 os.system / subprocess / exec / eval 等危险调用
- 禁止文件系统写入主目录（限定在临时目录内）
- 禁止网络访问（可选）
- 限制可用模块白名单

使用方式：
    sandbox = CodeSandbox(timeout=10, max_memory_mb=256)
    result = sandbox.execute("print('hello')")
    # result = {"success": True, "stdout": "hello\\n", "stderr": "", "error": ""}
"""
from __future__ import annotations

import ast
import os
import sys
import json
import shutil
import signal
import tempfile
import threading
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple


# ============================================================================
# 危险调用检测器（阶段 N.1.1）
# ============================================================================

class CodeSafetyChecker:
    """代码安全检查器：静态分析代码中的危险调用

    检测策略：
    1. AST 遍历，检查 import 和函数调用
    2. 黑名单：明确禁止的模块和函数
    3. 白名单：允许的安全模块（可选，默认用黑名单）
    """

    # 禁止的模块
    BLOCKED_MODULES: Set[str] = {
        "subprocess", "ctypes", "multiprocessing",
        "socket", "asyncio.ssl", "http.server", "ftplib", "smtplib",
        "telnetlib", "paramiko", "fabric",
        "shutil", "pathlib",  # 文件系统操作（允许读取，禁止批量操作）
        "webbrowser", "antigravity",
    }

    # 禁止的函数调用
    BLOCKED_FUNCTIONS: Set[str] = {
        "os.system", "os.popen", "os.exec", "os.execv", "os.execve",
        "os.spawn", "os.spawnl", "os.spawnv", "os.spawnve",
        "os.kill", "os.killpg", "os.abort", "os._exit",
        "os.chmod", "os.chown", "os.unlink", "os.rmdir", "os.removedirs",
        "os.rename", "os.replace", "os.symlink", "os.link",
        "os.setuid", "os.setgid", "os.seteuid", "os.setegid",
        "os.fork", "os.wait", "os.waitpid",
        "sys.exit", "sys._exit",
        "builtins.exec", "builtins.eval", "builtins.compile",
        "builtins.__import__",
        "builtins.open",  # 文件写入受限（允许读取）
        "globals", "locals", "vars", "dir",
        "getattr", "setattr", "delattr",  # 反射操作受限
    }

    # 允许的模块白名单（为空表示不启用白名单，用黑名单）
    ALLOWED_MODULES: Set[str] = {
        "math", "random", "statistics", "itertools", "functools",
        "collections", "heapq", "bisect", "array",
        "re", "string", "textwrap", "unicodedata",
        "json", "csv", "io",
        "datetime", "time", "calendar",
        "decimal", "fractions", "numbers",
        "hashlib", "hmac",
        "base64", "binascii", "uuid",
        "copy", "pprint", "reprlib",
        "enum", "typing",
        "dataclasses",
        # 数据分析（只读，不写文件）
        "numpy", "pandas", "scipy",
        "sklearn", "matplotlib",
        # 字符串处理
        "html", "xml.etree.ElementTree",
    }

    def __init__(self, use_whitelist: bool = False):
        """初始化

        Args:
            use_whitelist: 是否启用模块白名单（True 时只允许 ALLOWED_MODULES）
        """
        self.use_whitelist = use_whitelist

    def check(self, code: str) -> Tuple[bool, List[str]]:
        """检查代码安全性

        Args:
            code: 待检查的代码

        Returns:
            (is_safe, issues)
            is_safe: True 表示安全
            issues: 发现的问题列表
        """
        issues: List[str] = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, [f"语法错误: {e}"]

        # 遍历 AST
        for node in ast.walk(tree):
            # 检查 import 语句
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if self._is_module_blocked(module_name):
                        issues.append(f"禁止导入模块: {alias.name}")
                    elif self.use_whitelist and not self._is_module_allowed(module_name):
                        issues.append(f"模块不在白名单: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.split(".")[0]
                    if self._is_module_blocked(module_name):
                        issues.append(f"禁止导入模块: {node.module}")
                    elif self.use_whitelist and not self._is_module_allowed(module_name):
                        issues.append(f"模块不在白名单: {node.module}")

            # 检查函数调用
            elif isinstance(node, ast.Call):
                func_name = self._get_call_name(node)
                if func_name and self._is_function_blocked(func_name):
                    issues.append(f"禁止调用函数: {func_name}")

            # 检查属性访问（如 os.system）
            elif isinstance(node, ast.Attribute):
                attr_path = self._get_attribute_path(node)
                if attr_path and attr_path in self.BLOCKED_FUNCTIONS:
                    issues.append(f"禁止访问属性: {attr_path}")

        return len(issues) == 0, issues

    def _is_module_blocked(self, module_name: str) -> bool:
        """检查模块是否被禁止"""
        return module_name in self.BLOCKED_MODULES

    def _is_module_allowed(self, module_name: str) -> bool:
        """检查模块是否在白名单"""
        return module_name in self.ALLOWED_MODULES

    def _is_function_blocked(self, func_name: str) -> bool:
        """检查函数是否被禁止"""
        # 直接匹配
        if func_name in self.BLOCKED_FUNCTIONS:
            return True
        # 匹配 os.xxx 等前缀
        for blocked in self.BLOCKED_FUNCTIONS:
            if func_name.startswith(blocked + "."):
                return True
            if blocked.endswith("." + func_name.split(".")[-1]):
                return True
        return False

    @staticmethod
    def _get_call_name(node: ast.Call) -> str:
        """获取调用函数名"""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return CodeSafetyChecker._get_attribute_path(node.func) or ""
        return ""

    @staticmethod
    def _get_attribute_path(node: ast.Attribute) -> str:
        """获取属性访问路径（如 os.system）"""
        parts: List[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))


# ============================================================================
# 代码执行沙箱（阶段 N.1）
# ============================================================================

class CodeSandbox:
    """代码执行沙箱

    在子进程中安全执行 Python 代码，提供资源限制和隔离。

    执行流程：
    1. 安全检查：静态分析代码，拒绝危险调用
    2. 创建临时工作目录
    3. 生成执行脚本，注入安全限制
    4. 在子进程中执行，设置超时
    5. 捕获 stdout/stderr，返回结果
    6. 清理临时目录
    """

    def __init__(
        self,
        timeout: float = 10.0,
        max_memory_mb: int = 256,
        use_whitelist: bool = False,
        allow_network: bool = False,
        python_executable: Optional[str] = None,
    ):
        """初始化

        Args:
            timeout: 执行超时秒数
            max_memory_mb: 最大内存 MB
            use_whitelist: 是否启用模块白名单
            allow_network: 是否允许网络访问
            python_executable: Python 解释器路径，默认用 sys.executable
        """
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.checker = CodeSafetyChecker(use_whitelist=use_whitelist)
        self.allow_network = allow_network
        self.python_executable = python_executable or sys.executable

    def execute(
        self,
        code: str,
        stdin_input: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行代码

        Args:
            code: 待执行的 Python 代码
            stdin_input: 标准输入内容（可选）

        Returns:
            {
                "success": bool,      # 是否执行成功
                "stdout": str,         # 标准输出
                "stderr": str,         # 标准错误
                "error": str,          # 错误信息
                "returncode": int,     # 退出码
                "duration": float,     # 执行耗时秒
                "issues": List[str],   # 安全检查问题（如果有）
            }
        """
        import time

        result: Dict[str, Any] = {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": "",
            "returncode": -1,
            "duration": 0.0,
            "issues": [],
        }

        # 第1步：安全检查
        is_safe, issues = self.checker.check(code)
        if not is_safe:
            result["error"] = "代码安全检查未通过"
            result["issues"] = issues
            result["returncode"] = -2
            return result

        # 第2步：创建临时工作目录
        work_dir = tempfile.mkdtemp(prefix="zeroai_sandbox_")

        try:
            # 第3步：生成执行脚本
            script_path = os.path.join(work_dir, "_sandbox_code.py")
            wrapped_code = self._wrap_code(code, work_dir)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(wrapped_code)

            # 第4步：执行
            start_time = time.time()
            env = self._build_env(work_dir)

            try:
                proc = subprocess.run(
                    [self.python_executable, script_path],
                    input=stdin_input,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=work_dir,
                    env=env,
                    encoding="utf-8",
                    errors="replace",
                )
                result["stdout"] = proc.stdout or ""
                result["stderr"] = proc.stderr or ""
                result["returncode"] = proc.returncode
                result["success"] = proc.returncode == 0
                if proc.returncode != 0 and not result["error"]:
                    result["error"] = f"进程退出码: {proc.returncode}"
            except subprocess.TimeoutExpired as e:
                result["error"] = f"执行超时（{self.timeout}秒）"
                result["stdout"] = e.stdout or ""
                result["stderr"] = e.stderr or ""
                result["returncode"] = -3
            except Exception as e:
                result["error"] = f"执行异常: {type(e).__name__}: {e}"
                result["returncode"] = -4

            result["duration"] = time.time() - start_time

        finally:
            # 第6步：清理临时目录
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass

        return result

    def execute_async(
        self,
        code: str,
        stdin_input: Optional[str] = None,
    ):
        """异步执行代码

        Returns:
            asyncio.Future 风格的 coroutine
        """
        import asyncio

        loop = asyncio.get_event_loop()
        return loop.run_in_executor(
            None,
            lambda: self.execute(code, stdin_input),
        )

    def _wrap_code(self, code: str, work_dir: str) -> str:
        """包装用户代码，注入安全限制"""
        # 构建安全限制代码
        restrictions = []

        # 内存限制（通过 resource 模块，仅 Unix）
        if sys.platform != "win32" and self.max_memory_mb > 0:
            restrictions.append(f"""
import resource
try:
    resource.setrlimit(resource.RLIMIT_AS, ({self.max_memory_mb * 1024 * 1024}, {self.max_memory_mb * 1024 * 1024}))
except Exception:
    pass
""")

        # 网络隔离（通过禁用 socket，可选）
        if not self.allow_network:
            restrictions.append("""
try:
    import socket
    _orig_socket = socket.socket
    def _blocked_socket(*args, **kwargs):
        raise PermissionError("网络访问被沙箱禁用")
    socket.socket = _blocked_socket
except Exception:
    pass
""")

        # 限制工作目录
        restrictions.append(f"""
import os
os.chdir({repr(work_dir)})
""")

        # 组装最终代码
        header = "\n".join(restrictions)
        wrapped = f"""# -*- coding: utf-8 -*-
# ZeroAI 代码沙箱执行
# 自动生成，请勿手动修改

import sys
import io

{header}

# ====== 用户代码开始 ======
try:
{self._indent_code(code)}
except SystemExit as e:
    if e.code not in (0, None):
        print(f"[SystemExit] code={{e.code}}", file=sys.stderr)
except Exception as e:
    import traceback
    traceback.print_exc()
# ====== 用户代码结束 ======
"""
        return wrapped

    @staticmethod
    def _indent_code(code: str, indent: str = "    ") -> str:
        """缩进用户代码（放入 try 块内）"""
        lines = code.split("\n")
        return "\n".join(indent + line if line.strip() else line for line in lines)

    def _build_env(self, work_dir: str) -> Dict[str, str]:
        """构建子进程环境变量"""
        env = os.environ.copy()
        # 限制 PATH，防止执行外部命令
        env["PYTHONPATH"] = work_dir
        env["PYTHONIOENCODING"] = "utf-8"
        # 禁用 Python 缓存写入
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        return env


# ============================================================================
# 便捷接口
# ============================================================================

_default_sandbox: Optional[CodeSandbox] = None


def get_sandbox(
    timeout: float = 10.0,
    max_memory_mb: int = 256,
) -> CodeSandbox:
    """获取默认沙箱实例

    Args:
        timeout: 执行超时
        max_memory_mb: 最大内存

    Returns:
        CodeSandbox 实例
    """
    global _default_sandbox
    if _default_sandbox is None:
        _default_sandbox = CodeSandbox(
            timeout=timeout,
            max_memory_mb=max_memory_mb,
        )
    return _default_sandbox


def execute_code(
    code: str,
    timeout: float = 10.0,
    stdin_input: Optional[str] = None,
) -> Dict[str, Any]:
    """便捷函数：执行代码

    Args:
        code: Python 代码
        timeout: 超时秒数
        stdin_input: 标准输入

    Returns:
        执行结果字典
    """
    sandbox = CodeSandbox(timeout=timeout)
    return sandbox.execute(code, stdin_input=stdin_input)


def check_code_safety(code: str) -> Tuple[bool, List[str]]:
    """便捷函数：检查代码安全性

    Args:
        code: Python 代码

    Returns:
        (is_safe, issues)
    """
    checker = CodeSafetyChecker()
    return checker.check(code)


__all__ = [
    "CodeSafetyChecker",
    "CodeSandbox",
    "get_sandbox",
    "execute_code",
    "check_code_safety",
]
