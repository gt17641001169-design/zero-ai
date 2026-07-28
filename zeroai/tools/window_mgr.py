"""窗口管理工具

迁移来源：tui_agent.py 行 6187-6280

提供以下纯函数：
- active_window：获取当前焦点窗口信息（标题、应用、位置）
- list_windows：列出所有可见窗口
- read_screen_content：读取当前前台窗口的文字内容（通过 Windows UI Automation）

依赖：
- 标准库：ctypes, subprocess
- 可选：uiautomation（读取屏幕内容时使用，不可用时回退到窗口标题）
"""
import ctypes
import subprocess


def active_window() -> str:
    """获取当前焦点窗口信息（标题、应用、位置）

    迁移来源：tui_agent.py 行 6187-6213
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # 获取前台窗口句柄
        hwnd = user32.GetForegroundWindow()
        # 获取窗口标题
        length = user32.GetWindowTextLengthW(hwnd) + 1
        title = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, title, length)
        # 获取进程ID
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        # 获取进程名
        try:
            pr = subprocess.run(["tasklist", "/FI", f"PID eq {pid.value}", "/FO", "CSV", "/NH"],
                                capture_output=True, text=True, timeout=5)
            pname = pr.stdout.strip().split(",")[0].strip('"') if pr.stdout.strip() else "?"
        except Exception:
            pname = "?"
        # 获取窗口位置和大小
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return f"窗口：{title.value}\n应用：{pname}（PID: {pid.value}）\n位置：({rect.left}, {rect.top}) 大小：{rect.right - rect.left}x{rect.bottom - rect.top}"
    except Exception as e:
        return f"错误：{e}"


def list_windows() -> str:
    """列出所有可见窗口

    迁移来源：tui_agent.py 行 6216-6240
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        results = []
        def callback(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd) + 1
                if length > 1:
                    title = ctypes.create_unicode_buffer(length)
                    user32.GetWindowTextW(hwnd, title, length)
                    t = title.value.strip()
                    if t:
                        pid = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        results.append(f"  {t[:50]:<50} PID:{pid.value}")
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        user32.EnumWindows(WNDENUMPROC(callback), 0)
        if not results:
            return "(无可见窗口)"
        return f"可见窗口（{len(results)}个）：\n" + "\n".join(results[:30])
    except Exception as e:
        return f"错误：{e}"


def read_screen_content(max_length: int = 2000) -> str:
    """读取当前前台窗口的文字内容（通过 Windows UI Automation）

    迁移来源：tui_agent.py 行 6243-6280
    """
    try:
        import uiautomation as uia
        window = uia.GetForegroundControl()
        if not window:
            return "(无法获取前台窗口)"
        title = window.Name or ""
        classname = window.ClassName or ""
        # 读取窗口内可见文本
        texts = []
        def collect_text(ctrl, depth=0):
            if depth > 8 or len(texts) > 100:
                return
            try:
                name = ctrl.Name
                if name and name.strip() and name != title:
                    t = name.strip()
                    if len(t) > 200:
                        t = t[:200] + "..."
                    texts.append(t)
            except Exception:
                pass
            try:
                for child in ctrl.GetChildren():
                    collect_text(child, depth + 1)
            except Exception:
                pass
        collect_text(window)
        content = "\n".join(texts[:80])
        if len(content) > max_length:
            content = content[:max_length] + "\n...(截断)"
        return f"窗口：{title}\n类名：{classname}\n内容：\n{content}" if content.strip() else f"窗口：{title}\n(无可读文本)"
    except ImportError:
        # uiautomation 不可用时回退到窗口标题
        return active_window()
    except Exception as e:
        return f"读取失败：{e}"
