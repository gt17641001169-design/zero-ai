"""路径相关工具函数

迁移来源：tui_agent.py 行 28-199

提供资源路径智能查找、桌面目录定位、保存路径解析等功能。
支持开发模式（脚本目录）和 pip 安装模式（用户主目录）。

本模块无外部依赖，仅使用标准库 os/sys/pathlib。
"""
import os
import sys
from pathlib import Path

# ════════════════════════════════════════════════════════════════════
# 资源路径智能查找（支持开发模式和 pip 安装模式）
# 查找优先级：1. 脚本所在目录（开发模式）2. 环境变量 ZEROAI_HOME 3. 用户主目录 ~/.zeroai/
# ════════════════════════════════════════════════════════════════════
# 脚本所在目录（兼容源码运行和打包模式）
# 注意：使用 __file__ 的父目录的父目录，因为本文件位于 zeroai/core/ 下
# 但为了与 tui_agent.py 行为完全一致，使用 sys.path[0] 或当前工作目录回退
try:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
except Exception:
    _SCRIPT_DIR = os.getcwd()

_USER_HOME = os.path.expanduser("~")
_ZEROAI_USER_DIR = os.path.join(_USER_HOME, ".zeroai")

# 桌面目录缓存（兼容中英文 Windows / macOS / Linux，首次调用 _get_desktop_dir 时填充）
_DESKTOP_DIR_CACHE: str = ""


def _get_desktop_dir() -> str:
    """获取桌面目录路径（兼容中英文 Windows / macOS / Linux）。

    优先级：
    1. Windows: SHGetFolderPathW（CSIDL_DESKTOP，最可靠，能识别"桌面"重定向）
    2. Windows: USERPROFILE/Desktop 或 USERPROFILE/桌面
    3. macOS/Linux: ~/Desktop 或 ~/桌面
    4. Linux: XDG_DESKTOP_DIR 环境变量
    5. 回退: 用户主目录
    """
    global _DESKTOP_DIR_CACHE
    if _DESKTOP_DIR_CACHE:
        return _DESKTOP_DIR_CACHE

    # Windows: 用 SHGetFolderPathW 获取真实桌面路径
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_DESKTOP = 0x00
            if ctypes.windll.shell32.SHGetFolderPathW(0, 0x00, 0, 0, buf) == 0:
                if buf.value and os.path.isdir(buf.value):
                    _DESKTOP_DIR_CACHE = buf.value
                    return _DESKTOP_DIR_CACHE
        except Exception:
            pass
        # 回退：USERPROFILE 下找 Desktop / 桌面
        up = os.environ.get("USERPROFILE") or _USER_HOME
        for name in ("Desktop", "桌面"):
            p = os.path.join(up, name)
            if os.path.isdir(p):
                _DESKTOP_DIR_CACHE = p
                return _DESKTOP_DIR_CACHE

    # macOS / Linux
    for name in ("Desktop", "桌面"):
        p = os.path.join(_USER_HOME, name)
        if os.path.isdir(p):
            _DESKTOP_DIR_CACHE = p
            return _DESKTOP_DIR_CACHE

    # Linux XDG
    xdg = os.environ.get("XDG_DESKTOP_DIR")
    if xdg and os.path.isdir(xdg):
        _DESKTOP_DIR_CACHE = xdg
        return _DESKTOP_DIR_CACHE

    # 最终回退：用户主目录
    _DESKTOP_DIR_CACHE = _USER_HOME
    return _DESKTOP_DIR_CACHE


def _resolve_save_path(path: str, default_filename: str) -> str:
    """解析文档保存路径（默认保存到桌面）。

    规则：
    - path 为空：保存到 桌面/{default_filename}
    - path 只含文件名（无目录分隔符）：保存到 桌面/{path}
    - path 含完整路径：按 path 原样保存

    Args:
        path: 用户传入的路径
        default_filename: 默认文件名（如 "未命名.docx"）

    Returns:
        解析后的绝对路径
    """
    if not path:
        return os.path.join(_get_desktop_dir(), default_filename)
    # 判断是否只含文件名（无目录部分）
    if not os.path.dirname(path):
        return os.path.join(_get_desktop_dir(), path)
    return path


def _find_resource_dir(subdir: str) -> str:
    """智能查找资源目录（libs/、models/ 等），支持多位置查找。

    查找优先级：
    1. 脚本所在目录的子目录（开发模式：D:\\C\\C\\libs）
    2. 环境变量 ZEROAI_HOME 指定的子目录
    3. 用户主目录 ~/.zeroai/ 的子目录（pip 安装模式）

    返回第一个存在的目录；若都不存在，返回脚本所在目录的子目录（用于错误提示）。
    """
    candidates = [
        os.path.join(_SCRIPT_DIR, subdir),                    # 1. 开发模式
        os.path.join(os.environ.get("ZEROAI_HOME", ""), subdir),  # 2. 环境变量
        os.path.join(_ZEROAI_USER_DIR, subdir),               # 3. pip 安装模式
    ]
    for p in candidates:
        if p and os.path.isdir(p):
            return p
    # 默认返回脚本所在目录的子目录（用于错误提示和后续创建）
    return os.path.join(_SCRIPT_DIR, subdir)


def _ensure_user_dir() -> str:
    """确保用户主目录 ~/.zeroai/ 存在，返回路径"""
    if not os.path.isdir(_ZEROAI_USER_DIR):
        try:
            os.makedirs(_ZEROAI_USER_DIR, exist_ok=True)
        except OSError:
            pass
    return _ZEROAI_USER_DIR


# ====== 配置文件路径 ======
CONFIG_FILE = Path.home() / ".zeroai_config.json"
CUSTOM_MODELS_FILE = Path.home() / ".zeroai_models.json"


# ====== 资源路径（打包后从 _MEIPASS 读取，开发时从源码目录读取）======
def _get_resource_dir() -> Path:
    """获取资源目录路径（兼容 PyInstaller 打包和源码运行）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，资源在 _MEIPASS 中
        return Path(sys._MEIPASS) / "assets"
    else:
        # 源码运行：从本文件所在目录回溯到项目根目录的 assets
        # 本文件位于 zeroai/core/paths.py，项目根为上两级
        return Path(__file__).parent.parent.parent / "assets"


ASSETS_DIR = _get_resource_dir()
ICONS_DIR = ASSETS_DIR / "icons"
