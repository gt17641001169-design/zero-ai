"""Utility modules for ZeroAI"""
import platform
import os
import sys
from typing import Optional


def is_windows() -> bool:
    """Check if running on Windows"""
    return platform.system() == "Windows"


def is_linux() -> bool:
    """Check if running on Linux"""
    return platform.system() == "Linux"


def is_macos() -> bool:
    """Check if running on macOS"""
    return platform.system() == "Darwin"


def get_platform() -> str:
    """Get current platform"""
    return platform.system()


def get_script_dir() -> str:
    """Get the directory of the current script"""
    return os.path.dirname(os.path.abspath(__file__))


def get_user_dir() -> str:
    """Get user home directory for ZeroAI"""
    home = os.path.expanduser("~")
    zeroai_dir = os.path.join(home, ".zeroai")
    os.makedirs(zeroai_dir, exist_ok=True)
    return zeroai_dir


def get_desktop_dir() -> str:
    """Get desktop directory"""
    if is_windows():
        # Windows
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        desktop = winreg.QueryValueEx(key, "Desktop")[0]
        winreg.CloseKey(key)
        return desktop
    else:
        # Linux/macOS
        return os.path.join(os.path.expanduser("~"), "Desktop")


def safe_path(path: str, default_filename: str = "未命名.txt") -> str:
    """Safely resolve path, handling empty or relative paths"""
    if not path:
        return os.path.join(get_desktop_dir(), default_filename)
    
    # If only filename (no directory), use desktop
    if not os.path.dirname(path):
        return os.path.join(get_desktop_dir(), path)
    
    return path


def truncate_text(text: str, max_length: int = 8000) -> str:
    """Truncate text to max length with indicator"""
    if len(text) <= max_length:
        return text
    
    return text[:max_length] + f"\n\n[已截断，原始长度 {len(text)} 字符]"


def format_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def format_time(seconds: float) -> str:
    """Format time in human readable format"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}分钟"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}小时"
