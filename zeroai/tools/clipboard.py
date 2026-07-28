"""剪贴板工具

迁移来源：tui_agent.py 行 200-250

提供：
- _copy_to_clipboard：复制文本到系统剪贴板（Windows API，完整 Unicode 支持）

本模块仅使用标准库 ctypes，无外部依赖。
"""


def _copy_to_clipboard(text: str) -> bool:
    """复制文本到系统剪贴板（Windows API，完整 Unicode 支持）

    用 ctypes 直接调用 user32/kernel32，避免 clip.exe 的 GBK 编码问题。
    返回 True 表示成功，False 表示失败。
    """
    if not text:
        return False
    try:
        import ctypes

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # 64 位 Python 必须显式设置函数签名，否则句柄/指针会被截断为 32 位
        # HGLOBAL / LPVOID / HANDLE 在 64 位 Windows 上都是 64 位
        kernel32.GlobalAlloc.restype = ctypes.c_void_p  # HGLOBAL
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p  # LPVOID
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p  # HANDLE
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        # 编码为 UTF-16LE（Windows 内部字符串格式），末尾加 \0
        data_bytes = (text + "\0").encode("utf-16-le")

        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data_bytes))
            if not h_global:
                return False
            locked = kernel32.GlobalLock(h_global)
            if not locked:
                return False
            ctypes.memmove(locked, data_bytes, len(data_bytes))
            kernel32.GlobalUnlock(h_global)
            result = user32.SetClipboardData(CF_UNICODETEXT, h_global)
            return bool(result)
        finally:
            user32.CloseClipboard()
    except Exception:
        return False
