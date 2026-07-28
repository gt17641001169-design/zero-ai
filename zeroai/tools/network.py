"""网络与应用工具

迁移来源：tui_agent.py 行 2753-3091（APP_PATHS + 网络工具集）

提供以下纯函数：
- _search_executable：搜索可执行文件或文档
- open_app：打开桌面应用程序或任意文件
- web_search：网络搜索（百度/Bing）
- web_fetch：抓取网页（含 SSRF 防护）
- git_status：git 状态查询

依赖：
- zeroai.core.constants：PERMISSION_LEVEL
- 标准库：os, re, subprocess, urllib, pathlib
"""
import os
import re
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

from zeroai.core.constants import PERMISSION_LEVEL


# 应用路径硬编码映射（快速命中已知应用）
# 迁移来源：tui_agent.py 行 2753-2789
APP_PATHS = {
    # 通讯类
    "微信": r"D:\WeiXin\Weixin.exe",
    "wechat": r"D:\WeiXin\Weixin.exe",
    "weixin": r"D:\WeiXin\Weixin.exe",
    "qq": r"D:\QQ\QQ.exe",
    # 开发工具
    "vscode": r"D:\Microsoft VS Code\Code.exe",
    "vs code": r"D:\Microsoft VS Code\Code.exe",
    "code": r"D:\Microsoft VS Code\Code.exe",
    "pycharm": r"D:\pycharm\PyCharm 2025.3.2.1\bin\pycharm64.exe",
    # 浏览器
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "浏览器": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    # 系统自带应用
    "记事本": "notepad.exe",
    "notepad": "notepad.exe",
    "计算器": "calc.exe",
    "calc": "calc.exe",
    "资源管理器": "explorer.exe",
    "explorer": "explorer.exe",
    "文件资源管理器": "explorer.exe",
    "画图": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "写字板": "write.exe",
    "write": "write.exe",
    "任务管理器": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "控制面板": "control.exe",
    "control": "control.exe",
    "注册表": "regedit.exe",
    "regedit": "regedit.exe",
    "cmd": "cmd.exe",
    "命令提示符": "cmd.exe",
    "powershell": "powershell.exe",
    "终端": "powershell.exe",
}


def _search_executable(name: str) -> str:
    """在本地自动搜索可执行文件或文档，返回找到的完整路径
    搜索顺序：
    1. APP_PATHS 硬编码映射（快速命中已知应用）
    2. 系统 PATH 环境变量
    3. Windows 注册表（App Paths / uninstall / exe 找到安装路径）
    4. 常见安装目录递归搜索（D:/ C:/Program Files 等）

    迁移来源：tui_agent.py 行 2792-2913
    """
    key = name.lower().strip()

    # 1. 硬编码映射
    path = APP_PATHS.get(key) or APP_PATHS.get(name)
    if path:
        if "\\" not in path or Path(path).exists():
            return path

    # 2. 系统 PATH
    for dir_path in os.environ.get("PATH", "").split(os.pathsep):
        for ext in ("", ".exe", ".bat", ".cmd", ".msi", ".lnk"):
            candidate = Path(dir_path) / f"{name}{ext}"
            if candidate.exists():
                return str(candidate)

    # 3. 注册表搜索（App Paths）
    try:
        import winreg
        # HKLM App Paths
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}.exe") as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if val and Path(val).exists():
                        return val
            except (FileNotFoundError, OSError):
                pass
        # HKLM Uninstall：搜索 DisplayName 匹配的应用，找 InstallLocation
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall") as k:
                    i = 0
                    while True:
                        try:
                            sub_name = winreg.EnumKey(k, i)
                            i += 1
                            with winreg.OpenKey(k, sub_name) as sk:
                                try:
                                    display, _ = winreg.QueryValueEx(sk, "DisplayName")
                                    if key in display.lower() or display.lower() in key:
                                        try:
                                            loc, _ = winreg.QueryValueEx(sk, "InstallLocation")
                                            if loc:
                                                # 在安装目录中搜索 exe
                                                for p in Path(loc).rglob("*.exe"):
                                                    if key in p.stem.lower():
                                                        return str(p)
                                                # 返回安装目录的第一个 exe
                                                for p in Path(loc).rglob("*.exe"):
                                                    return str(p)
                                        except (FileNotFoundError, OSError):
                                            pass
                                except (FileNotFoundError, OSError):
                                    pass
                        except OSError:
                            break
            except (FileNotFoundError, OSError):
                pass
    except ImportError:
        pass

    # 4. 常见安装目录搜索
    search_dirs = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"D:\\",
        r"D:\Program Files",
        r"D:\Program Files (x86)",
        r"D:\Microsoft VS Code",
        r"D:\Weixin",
        r"D:\QQ",
        r"D:\pycharm",
        os.path.expanduser("~\\AppData\\Local"),
        os.path.expanduser("~\\AppData\\Roaming"),
        os.path.expanduser("~\\Desktop"),
    ]
    # 去重
    seen = set()
    unique_dirs = []
    for d in search_dirs:
        if d not in seen and Path(d).exists():
            seen.add(d)
            unique_dirs.append(d)

    for dir_path in unique_dirs:
        # 限制搜索深度 3 层，避免太慢
        try:
            base = Path(dir_path)
            for p in base.glob("*"):
                # 直接匹配文件名
                if p.is_file():
                    stem_lower = p.stem.lower()
                    name_lower = name.lower().replace(".exe", "").replace(".lnk", "")
                    if name_lower == stem_lower or name_lower in stem_lower:
                        return str(p)
                elif p.is_dir():
                    # 搜索子目录（1层）
                    try:
                        for sub in p.glob("*.exe"):
                            stem_lower = sub.stem.lower()
                            name_lower = name.lower().replace(".exe", "")
                            if name_lower in stem_lower or stem_lower in name_lower:
                                return str(sub)
                        for sub in p.glob("*.lnk"):
                            stem_lower = sub.stem.lower()
                            name_lower = name.lower().replace(".lnk", "")
                            if name_lower in stem_lower or stem_lower in name_lower:
                                return str(sub)
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            continue

    return ""


def open_app(name: str) -> str:
    """打开桌面应用程序或任意文件
    自动在本地搜索后打开，保证能打开任何文件：
    1. 先查 APP_PATHS 硬编码映射
    2. 再查系统 PATH 环境变量
    3. 再查注册表 App Paths / Uninstall
    4. 最后在常见安装目录递归搜索
    如果 name 是已存在的文件路径，直接用系统默认程序打开

    迁移来源：tui_agent.py 行 2916-2948
    """
    # 如果 name 是已存在的文件路径，直接打开
    direct_path = Path(name)
    if direct_path.exists():
        try:
            os.startfile(str(direct_path))
            return f"已打开文件：{name}"
        except Exception as e:
            return f"打开失败：{e}"

    # 自动搜索
    found_path = _search_executable(name)
    if not found_path:
        return f"未在本地找到「{name}」。已搜索：APP_PATHS → PATH → 注册表 → 常见安装目录。请提供完整路径。"

    try:
        subprocess.Popen(found_path)
        return f"已启动：{name}\n路径：{found_path}"
    except Exception as e:
        # 尝试用 os.startfile 作为后备
        try:
            os.startfile(found_path)
            return f"已打开：{name}\n路径：{found_path}"
        except Exception:
            return f"启动失败：{e}"


def web_search(query: str, num_results: int = 5) -> str:
    """网络搜索（百度优先，Bing CN 备用，Bing 国际版第三）

    迁移来源：tui_agent.py 行 2951-3042
    """
    q = urllib.parse.quote(query)
    _FILTERS_BAIDU = ("baidu.com", "baidustatic", "bdstatic", "baiduimg",
                      "baidupcs", "bcebos", "baiducontent")
    _FILTERS_BING = ("bing.com", "microsoft.com", "go.microsoft", "live.com",
                     "msn.com", "sogou.com", ".css", ".js", ".png", ".jpg")

    def _extract_baidu_results(html, max_results):
        results = []
        blocks = re.findall(r'<div class="c-container[^"]*"[^>]*>([\s\S]*?)</div>', html)
        for block in blocks[:max_results * 3]:
            h3_m = re.search(r'<h3[^>]*>.*?href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if h3_m:
                title = re.sub(r"<[^>]+>", "", h3_m.group(2)).strip()
                link = h3_m.group(1)
                if not link.startswith("http"):
                    mu = re.search(r'mu="([^"]*)"', block)
                    if mu:
                        link = mu.group(1)
                if link.startswith("http") and title and len(title) > 2 and not any(f in link for f in _FILTERS_BAIDU):
                    results.append(f"{title}\n  {link}")
                    if len(results) >= max_results:
                        break
        return results

    def _extract_bing_results(html, max_results):
        results = []
        for block in re.findall(r'<li class="b_algo"[^>]*>([\s\S]*?)</li>', html):
            hrefs = re.findall(r'href="(https?://[^"]+)"', block)
            t = re.search(r"<a[^>]*>(.*?)</a>", block, re.DOTALL)
            title = re.sub(r"<[^>]+>", "", t.group(1)).strip() if t else ""
            link = next((h for h in hrefs if not any(f in h for f in _FILTERS_BING)), "")
            if link and title and len(title) > 3:
                results.append(f"{title}\n  {link}")
                if len(results) >= max_results:
                    return results
        return results

    _UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"

    # 方案1：百度搜索（国内首选，超时 15 秒）
    try:
        url = f"https://www.baidu.com/s?wd={q}&rn={num_results * 2}"
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        r = _extract_baidu_results(html, num_results)
        if r:
            return "\n\n".join(r)
    except Exception:
        pass

    # 方案2：Bing 中国版（超时 20 秒）
    try:
        url = f"https://cn.bing.com/search?q={q}&count={num_results * 2}"
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://cn.bing.com/",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        r = _extract_bing_results(html, num_results)
        if r:
            return "\n\n".join(r)
    except Exception:
        pass

    # 方案3：Bing 国际版（超时 20 秒）
    try:
        q_bp = urllib.parse.quote_plus(query)
        url = f"https://www.bing.com/search?q={q_bp}&count={num_results * 2}&setlang=zh-CN&cc=cn"
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        r = _extract_bing_results(html, num_results)
        if r:
            return "\n\n".join(r)
    except Exception:
        pass

    return "(搜索失败：所有搜索引擎均不可达，请检查网络连接或稍后重试)"

def web_fetch(url: str, max_length: int = 4000) -> str:
    """全权限模式：可访问内网/任意 URL，无 SSRF 限制

    迁移来源：tui_agent.py 行 3044-3077
    """
    # SSRF 防护（仅受限模式生效）
    if PERMISSION_LEVEL != "full":
        import ipaddress
        import socket
        try:
            # 解析域名获取 IP
            host = urllib.parse.urlparse(url).hostname
            if host:
                try:
                    ip = socket.gethostbyname(host)
                    ip_obj = ipaddress.ip_address(ip)
                    # 拦截内网/本地地址
                    if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
                        return f"SSRF 防护：禁止访问内网地址 {ip}"
                except (socket.gaierror, ValueError):
                    pass
        except Exception:
            pass
    # 全权限：max_length 默认放大到 16000
    if PERMISSION_LEVEL == "full" and max_length == 4000:
        max_length = 16000
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html)
        text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_length] if len(text) > max_length else text
    except Exception as e:
        return f"抓取错误：{e}"


def git_status(repo_path: str = ".") -> str:
    """git 状态查询

    迁移来源：tui_agent.py 行 3080-3091
    """
    try:
        r = subprocess.run(["git", "status", "--short", "--branch"],
                          capture_output=True, text=True, timeout=10, cwd=repo_path)
        branch = subprocess.run(["git", "branch", "--show-current"],
                               capture_output=True, text=True, timeout=5, cwd=repo_path)
        out = f"分支: {branch.stdout.strip()}\n{r.stdout.strip()}"
        return out if out.strip() else "(无变更)"
    except FileNotFoundError:
        return "错误：git 未安装"
    except Exception as e:
        return f"错误：{e}"
