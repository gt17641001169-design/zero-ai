"""
_zig_bindings.py - ZeroAI TUI Zig 渲染层 Python 绑定

通过 ctypes 加载 zig_render 共享库，提供与 _renderer.c 等价但更高性能的
缓冲区 diff 接口。

加载顺序：
    1. 包内 zeroai_tui/zig_render.dll（build.zig 安装到此）
    2. 项目根目录 zig_render.dll（开发期手动编译）
    3. 加载失败则 HAS_ZIG_RENDERER = False，回退到 _renderer.c 或纯 Python

颜色 ID 映射：
    Python 侧的 Color 类用 ANSI 字符串（如 "\\033[31m"）表示颜色，
    Zig 侧用 int16 ID（0-15）表示。本模块负责两者互转。

StyleStruct ABI（8 字节，与 zig_render.zig 的 StyleStruct 对齐）：
    offset 0: bold      (u8)
    offset 1: dim       (u8)
    offset 2: italic    (u8)
    offset 3: underline (u8)
    offset 4: fg_id     (i16)
    offset 6: bg_id     (i16)
"""
import ctypes
import os
import sys
from typing import List, Optional, Tuple

# ============================================================================
# StyleStruct（C ABI，必须与 zig_render.zig 的 StyleStruct 完全一致）
# ============================================================================

class StyleStruct(ctypes.Structure):
    """Zig 侧 StyleStruct 的 ctypes 镜像（8 字节）"""
    _fields_ = [
        ("bold", ctypes.c_uint8),
        ("dim", ctypes.c_uint8),
        ("italic", ctypes.c_uint8),
        ("underline", ctypes.c_uint8),
        ("fg_id", ctypes.c_int16),
        ("bg_id", ctypes.c_int16),
    ]

    def __repr__(self) -> str:
        return (
            f"StyleStruct(bold={self.bold}, dim={self.dim}, "
            f"italic={self.italic}, underline={self.underline}, "
            f"fg_id={self.fg_id}, bg_id={self.bg_id})"
        )


# ============================================================================
# 颜色字符串 <-> ID 映射表
# 与 terminal.py 的 Color 类保持一致
# ============================================================================

# ANSI 颜色字符串 -> ID
_COLOR_TO_ID = {
    # 基本前景色
    "\033[30m": 0,   "\033[31m": 1,  "\033[32m": 2,  "\033[33m": 3,
    "\033[34m": 4,   "\033[35m": 5,  "\033[36m": 6,  "\033[37m": 7,
    # 亮色前景色
    "\033[90m": 8,   "\033[91m": 9,  "\033[92m": 10, "\033[93m": 11,
    "\033[94m": 12,  "\033[95m": 13, "\033[96m": 14, "\033[97m": 15,
    # 基本背景色（注意：bg_id 单独编码，不与 fg 冲突）
    "\033[40m": 0,   "\033[41m": 1,  "\033[42m": 2,  "\033[43m": 3,
    "\033[44m": 4,   "\033[45m": 5,  "\033[46m": 6,  "\033[47m": 7,
    # 亮色背景色
    "\033[100m": 8,  "\033[101m": 9, "\033[102m": 10, "\033[103m": 11,
    "\033[104m": 12, "\033[105m": 13, "\033[106m": 14, "\033[107m": 15,
}


def color_str_to_id(color_str: Optional[str]) -> int:
    """将 ANSI 颜色字符串转换为 ID，无法识别返回 -1"""
    if not color_str:
        return -1
    return _COLOR_TO_ID.get(color_str, -1)


# ============================================================================
# Zig 共享库加载
# ============================================================================

def _find_zig_lib() -> Optional[str]:
    """查找 zig_render 共享库路径

    搜索顺序（严谨的多层降级）：
        0. 环境变量 ZEROAI_ZIG_LIB（开发者强制指定）
        1. 包内（zeroai_tui/）—— build.zig 安装目标
        2. 项目根 zeroai-tui/
        3. src/ 目录（开发期 zig build 输出）
        4. zig-out/bin、zig-out/lib（Zig 标准构建输出）
        5. Python sys.prefix/Lib/site-packages（pip 安装位置）
        6. 系统库目录（PATH / LD_LIBRARY_PATH / DYLD_LIBRARY_PATH）

    Returns:
        库文件完整路径，未找到返回 None
    """
    # 库文件名（按平台）
    if sys.platform == "win32":
        lib_names = ["zig_render.dll", "libzig_render.dll"]
    elif sys.platform == "darwin":
        lib_names = ["libzig_render.dylib", "zig_render.dylib"]
    else:
        lib_names = ["libzig_render.so", "zig_render.so"]

    # 0. 环境变量强制指定（开发者优先级最高）
    env_path = os.environ.get("ZEROAI_ZIG_LIB")
    if env_path and os.path.isfile(env_path):
        return env_path

    # 1-4. 包内 / 项目根 / src / zig-out
    package_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(package_dir)
    src_dir = os.path.join(project_root, "src")
    zig_out_bin = os.path.join(project_root, "zig-out", "bin")
    zig_out_lib = os.path.join(project_root, "zig-out", "lib")

    search_dirs = [
        package_dir,        # build.zig 安装目标
        project_root,       # 开发期手动编译
        src_dir,            # src/ 输出
        zig_out_bin,        # zig build 默认输出
        zig_out_lib,
    ]

    for d in search_dirs:
        if not d or not os.path.isdir(d):
            continue
        for name in lib_names:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return path

    # 5. Python 安装位置（pip install 后产物位置）
    py_search_dirs = [
        sys.prefix,
        os.path.join(sys.prefix, "Lib"),
        os.path.join(sys.prefix, "lib"),
    ]
    # 虚拟环境场景
    if hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix:
        py_search_dirs.extend([
            sys.base_prefix,
            os.path.join(sys.base_prefix, "Lib"),
        ])
    # site-packages
    try:
        import site
        for sp in site.getsitepackages():
            py_search_dirs.append(sp)
        py_search_dirs.append(site.getusersitepackages())
    except Exception:
        pass

    for d in py_search_dirs:
        if not d or not os.path.isdir(d):
            continue
        for name in lib_names:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return path

    # 6. 系统库目录
    if sys.platform == "win32":
        # Windows: 搜索 PATH 中的目录
        path_env = os.environ.get("PATH", "")
        for d in path_env.split(os.pathsep):
            if not d or not os.path.isdir(d):
                continue
            for name in lib_names:
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    return path
    else:
        # Unix: LD_LIBRARY_PATH / DYLD_LIBRARY_PATH
        for env_var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            lib_path = os.environ.get(env_var, "")
            for d in lib_path.split(os.pathsep):
                if not d or not os.path.isdir(d):
                    continue
                for name in lib_names:
                    path = os.path.join(d, name)
                    if os.path.isfile(path):
                        return path
        # 标准系统库目录
        for d in ("/usr/lib", "/usr/local/lib", "/opt/local/lib", "/lib"):
            if not os.path.isdir(d):
                continue
            for name in lib_names:
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    return path

    return None


def _diagnose_zig_load_failure() -> str:
    """诊断 Zig 加载失败原因（用于自检和调试）

    Returns:
        诊断信息字符串
    """
    lib_path = _find_zig_lib()

    # 库找到且加载成功的情况
    if lib_path is not None and _zig_load_error is None:
        return f"Zig 库加载成功: {lib_path}"

    # 库找到但加载失败
    if lib_path is not None and _zig_load_error is not None:
        reasons = []
        reasons.append(f"Zig 库已找到但加载失败: {lib_path}")
        reasons.append(f"失败原因: {_zig_load_error}")
        reasons.append("")
        reasons.append("可能原因与修复：")
        reasons.append("  1. ABI 不兼容：重新 zig build 并替换共享库")
        reasons.append("  2. 依赖缺失：检查 Zig 运行时依赖（Linux 用 ldd，Windows 用 dumpbin）")
        reasons.append("  3. 权限问题：检查文件读写权限")
        reasons.append("  4. 32/64 位不匹配：确认 Python 与 Zig 都是同一架构")
        reasons.append("")
        reasons.append("当前会自动降级到 C 扩展或纯 Python 实现，不影响功能")
        return "\n".join(reasons)

    # 库未找到
    reasons = []
    reasons.append("未找到 zig_render 共享库，已搜索以下位置：")

    package_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(package_dir)

    searched = [
        ("ZEROAI_ZIG_LIB 环境变量", os.environ.get("ZEROAI_ZIG_LIB", "(未设置)")),
        ("包内目录", package_dir),
        ("项目根", project_root),
        ("src/", os.path.join(project_root, "src")),
        ("zig-out/bin", os.path.join(project_root, "zig-out", "bin")),
        ("zig-out/lib", os.path.join(project_root, "zig-out", "lib")),
        ("sys.prefix", sys.prefix),
        ("site-packages", "(多个)"),
    ]

    if sys.platform != "win32":
        for env_var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            searched.append((env_var, os.environ.get(env_var, "(未设置)")))
        searched.append(("/usr/lib", "/usr/local/lib"))

    for label, path in searched:
        reasons.append(f"  - {label}: {path}")

    reasons.append("")
    reasons.append("修复方法：")
    reasons.append("  1. 在 zeroai-tui/ 目录运行 'zig build -Doptimize=ReleaseFast'")
    reasons.append("  2. 或设置环境变量 ZEROAI_ZIG_LIB 指向 zig_render.dll 路径")
    reasons.append("  3. 当前会自动降级到 C 扩展或纯 Python 实现，不影响功能")

    return "\n".join(reasons)


def _load_zig_lib():
    """加载 zig_render 共享库，失败返回 None

    失败原因会记录到 _zig_load_error 全局变量，用于自检诊断。
    """
    global _zig_load_error
    lib_path = _find_zig_lib()
    if lib_path is None:
        _zig_load_error = "library not found"
        return None

    try:
        # Windows: 使用 LOAD_WITH_ALTERED_SEARCH_PATH 让依赖 DLL 也能加载
        if sys.platform == "win32":
            lib = ctypes.CDLL(lib_path, mode=0x8)
        else:
            lib = ctypes.CDLL(lib_path)
    except OSError as e:
        _zig_load_error = f"CDLL load failed: {e}"
        return None

    # 验证 zig_diff_buffers 符号存在
    try:
        func = getattr(lib, "zig_diff_buffers", None)
        if func is None:
            _zig_load_error = f"symbol 'zig_diff_buffers' not found in {lib_path}"
            try:
                DYNLIB_CLOSE = getattr(lib, "_handle", None)
                # ctypes 句柄在 GC 时会自动关闭，无需手动 close
            except Exception:
                pass
            return None
    except Exception as e:
        _zig_load_error = f"symbol lookup failed: {e}"
        return None

    # 配置 zig_diff_buffers 函数签名
    # c_int zig_diff_buffers(
    #     [*]const u8, [*]const StyleStruct,
    #     [*]const u8, [*]const StyleStruct,
    #     usize, usize,
    #     [*]u8, usize, *usize
    # )
    try:
        lib.zig_diff_buffers.argtypes = [
            ctypes.c_char_p,                          # current_chars
            ctypes.POINTER(StyleStruct),              # current_styles
            ctypes.c_char_p,                          # next_chars
            ctypes.POINTER(StyleStruct),              # next_styles
            ctypes.c_size_t,                          # rows
            ctypes.c_size_t,                          # cols
            ctypes.c_char_p,                          # output
            ctypes.c_size_t,                          # output_capacity
            ctypes.POINTER(ctypes.c_size_t),          # output_len
        ]
        lib.zig_diff_buffers.restype = ctypes.c_int
    except Exception as e:
        _zig_load_error = f"signature config failed: {e}"
        return None

    _zig_load_error = None
    return lib


# 加载状态记录（用于诊断）
_zig_load_error: Optional[str] = None


# 尝试加载
_zig_lib = _load_zig_lib()
HAS_ZIG_RENDERER = _zig_lib is not None


# ============================================================================
# 高层 API
# ============================================================================

def _style_to_struct(style) -> StyleStruct:
    """将 Python Style 对象转换为 StyleStruct

    支持 zeroai_tui.renderer.Style 和兼容的鸭子类型对象。
    """
    if style is None:
        return StyleStruct()

    # 颜色字符串转 ID
    fg_id = -1
    bg_id = -1
    fg = getattr(style, "fg", None)
    bg = getattr(style, "bg", None)
    if fg is not None:
        fg_id = color_str_to_id(fg)
    if bg is not None:
        bg_id = color_str_to_id(bg)

    return StyleStruct(
        bold=1 if getattr(style, "bold", False) else 0,
        dim=1 if getattr(style, "dim", False) else 0,
        italic=1 if getattr(style, "italic", False) else 0,
        underline=1 if getattr(style, "underline", False) else 0,
        fg_id=fg_id,
        bg_id=bg_id,
    )


def _flatten_buffer(
    buffer: List[List[str]],
    styles: List[List],
    rows: int,
    cols: int,
) -> Tuple[bytes, "ctypes.Array[StyleStruct]"]:
    """将 Python 二维列表缓冲区扁平化为 ctypes 数组

    Returns:
        (chars_bytes, styles_array)
        - chars_bytes: rows*cols 字节的 bytes 对象
        - styles_array: rows*cols 个 StyleStruct 的 ctypes 数组
    """
    # 扁平化字符（每个单元格取首字符的 ASCII 码，非 ASCII 用空格替代）
    char_list = []
    for row in range(rows):
        row_chars = buffer[row] if row < len(buffer) else []
        for col in range(cols):
            if col < len(row_chars):
                ch = row_chars[col]
                if isinstance(ch, str) and len(ch) > 0:
                    # 取首字符，转 ASCII（Zig 端目前只支持单字节）
                    byte = ord(ch[0]) if ord(ch[0]) < 256 else ord(' ')
                    char_list.append(byte)
                else:
                    char_list.append(ord(' '))
            else:
                char_list.append(ord(' '))

    chars_bytes = bytes(char_list)

    # 扁平化样式
    styles_arr = (StyleStruct * (rows * cols))()
    for row in range(rows):
        row_styles = styles[row] if row < len(styles) else []
        for col in range(cols):
            if col < len(row_styles):
                styles_arr[row * cols + col] = _style_to_struct(row_styles[col])
            else:
                styles_arr[row * cols + col] = StyleStruct()

    return chars_bytes, styles_arr


def diff_buffers(
    current_buffer: List[List[str]],
    current_styles: List[List],
    next_buffer: List[List[str]],
    next_styles: List[List],
    rows: int,
    cols: int,
) -> Optional[str]:
    """比较两个缓冲区，生成 ANSI 差异输出（与 _renderer.diff_buffers 等价）

    Args:
        current_buffer: 当前帧字符二维列表 [row][col] -> str
        current_styles: 当前帧样式二维列表 [row][col] -> Style|None
        next_buffer: 下一帧字符二维列表
        next_styles: 下一帧样式二维列表
        rows, cols: 缓冲区尺寸

    Returns:
        ANSI 差异字符串，或 None 表示调用失败（调用方应回退到 _renderer.c）
    """
    if not HAS_ZIG_RENDERER:
        return None

    # 扁平化输入缓冲区
    curr_chars, curr_styles = _flatten_buffer(current_buffer, current_styles, rows, cols)
    next_chars, next_styles = _flatten_buffer(next_buffer, next_styles, rows, cols)

    # 分配输出缓冲区
    # 最坏情况：每个单元格都变化，每个单元格最多输出：
    #   光标序列(14) + 样式序列(30) + 字符(1) = 45 字节
    # + 末尾重置(4)
    output_capacity = rows * cols * 48 + 16
    output_buf = ctypes.create_string_buffer(output_capacity)
    output_len = ctypes.c_size_t(0)

    # 调用 Zig 函数
    rc = _zig_lib.zig_diff_buffers(
        curr_chars,
        curr_styles,
        next_chars,
        next_styles,
        ctypes.c_size_t(rows),
        ctypes.c_size_t(cols),
        output_buf,
        ctypes.c_size_t(output_capacity),
        ctypes.byref(output_len),
    )

    if rc != 0:
        # -1: 参数错误, -2: 缓冲区不足
        # 两种情况都回退到 Python 实现
        return None

    # 返回 ANSI 字符串
    return output_buf.raw[:output_len.value].decode("utf-8", errors="replace")


# ============================================================================
# 自检
# ============================================================================

def self_test() -> bool:
    """快速自检：确认 Zig 库可用且 diff_buffers 工作正常

    Returns:
        True 表示自检通过
    """
    if not HAS_ZIG_RENDERER:
        return False

    # 简单测试：1x2 缓冲区，第二格字符变化
    curr_buf = [["a", "b"]]
    next_buf = [["a", "X"]]
    curr_styles = [[None, None]]
    next_styles = [[None, None]]

    result = diff_buffers(curr_buf, curr_styles, next_buf, next_styles, 1, 2)
    if result is None:
        return False

    # 应该包含 X 和重置序列
    return "X" in result and "\033[0m" in result


if __name__ == "__main__":
    # 命令行自检
    print(f"HAS_ZIG_RENDERER = {HAS_ZIG_RENDERER}")
    if HAS_ZIG_RENDERER:
        print(f"Library path: {_find_zig_lib()}")
        print(f"Self-test: {'PASS' if self_test() else 'FAIL'}")
    else:
        print("Zig library not found. Run 'zig build' in zeroai-tui/ first.")
        print()
        print(_diagnose_zig_load_failure())
