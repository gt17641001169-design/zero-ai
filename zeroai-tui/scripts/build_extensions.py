"""跨平台 C/Zig 扩展构建脚本

严格按架构图执行三层构建：
    1. Zig 共享库（zig_render.dll / libzig_render.so / libzig_render.dylib）
       - 失败不中断，C 扩展可独立工作（运行时自动降级）
    2. C 扩展（_renderer.pyd / _terminal.pyd）
       - 必须成功，是 Python 的唯一 C 入口
    3. 产物验证（导入测试 + ABI 自检）

跨平台支持：
    - Windows: MSVC / MinGW
    - macOS: Clang
    - Linux: GCC / Clang

用法：
    python zeroai-tui/scripts/build_extensions.py
    python zeroai-tui/scripts/build_extensions.py --skip-zig
    python zeroai-tui/scripts/build_extensions.py --check-only
    python zeroai-tui/scripts/build_extensions.py --release
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple


# ============================================================================
# 路径常量
# ============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
TUI_ROOT = SCRIPT_DIR.parent                  # zeroai-tui/
PACKAGE_DIR = TUI_ROOT / "zeroai_tui"         # zeroai-tui/zeroai_tui/
SRC_DIR = PACKAGE_DIR / "src"                 # zeroai-tui/zeroai_tui/src/
SETUP_PY = TUI_ROOT / "setup.py"
BUILD_ZIG = TUI_ROOT / "build.zig"


# ============================================================================
# 平台检测
# ============================================================================
def detect_platform() -> Dict[str, str]:
    """检测平台信息"""
    info = {
        "system": platform.system(),        # Windows / Darwin / Linux
        "machine": platform.machine(),      # AMD64 / ARM64 / x86_64
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
    }

    # 共享库后缀
    if info["system"] == "Windows":
        info["lib_suffix"] = ".dll"
        info["ext_suffix"] = ".pyd"
    elif info["system"] == "Darwin":
        info["lib_suffix"] = ".dylib"
        info["ext_suffix"] = ".so"
    else:
        info["lib_suffix"] = ".so"
        info["ext_suffix"] = ".so"

    return info


def find_zig_executable() -> Optional[str]:
    """查找 zig 可执行文件"""
    # PATH 中查找
    zig_in_path = shutil.which("zig")
    if zig_in_path:
        return zig_in_path

    # Windows 常见安装路径
    if sys.platform == "win32":
        common_paths = [
            r"C:\zig\zig.exe",
            r"C:\Program Files\Zig\zig.exe",
            r"C:\Program Files (x86)\Zig\zig.exe",
            str(Path.home() / "zig" / "zig.exe"),
        ]
    else:
        common_paths = [
            "/usr/local/bin/zig",
            "/usr/bin/zig",
            "/opt/zig/zig",
            str(Path.home() / ".local" / "bin" / "zig"),
        ]

    for path in common_paths:
        if Path(path).is_file():
            return path
    return None


def find_c_compiler() -> Optional[str]:
    """查找 C 编译器"""
    # Windows: 优先 MSVC，再 MinGW
    if sys.platform == "win32":
        for cmd in ["cl.exe", "gcc.exe", "clang.exe"]:
            if shutil.which(cmd):
                return cmd
    else:
        for cmd in ["gcc", "clang", "cc"]:
            if shutil.which(cmd):
                return cmd
    return None


# ============================================================================
# 构建步骤
# ============================================================================
def build_zig_library(release: bool = True) -> Tuple[bool, str]:
    """构建 Zig 共享库

    Returns:
        (success, message)
    """
    zig_exe = find_zig_executable()
    if zig_exe is None:
        return False, "zig 可执行文件未找到（可忽略，C 扩展会独立工作）"

    if not BUILD_ZIG.exists():
        return False, f"build.zig 不存在: {BUILD_ZIG}"

    # 检查 zig 版本
    try:
        result = subprocess.run(
            [zig_exe, "version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False, f"zig version 返回错误: {result.stderr}"
        zig_version = result.stdout.strip()
    except (subprocess.TimeoutExpired, Exception) as e:
        return False, f"zig version 调用失败: {e}"

    # 构建命令
    cmd = [zig_exe, "build"]
    if release:
        cmd.append("-Doptimize=ReleaseFast")

    print(f"[build] zig 版本: {zig_version}")
    print(f"[build] 执行: {' '.join(cmd)}")
    print(f"[build] 工作目录: {TUI_ROOT}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(TUI_ROOT),
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            return False, (
                f"zig build 失败 (code={result.returncode})\n"
                f"stdout: {result.stdout[:500]}\n"
                f"stderr: {result.stderr[:500]}"
            )

        # 验证产物
        plat = detect_platform()
        lib_name = f"libzig_render{plat['lib_suffix']}"
        # Windows 上也可能叫 zig_render.dll
        alt_name = f"zig_render{plat['lib_suffix']}" if sys.platform == "win32" else lib_name

        search_dirs = [
            PACKAGE_DIR,
            TUI_ROOT / "zig-out" / "bin",
            TUI_ROOT / "zig-out" / "lib",
            TUI_ROOT / "zig-out",
        ]

        for d in search_dirs:
            for name in [lib_name, alt_name]:
                p = d / name
                if p.exists():
                    # 复制到包目录
                    target = PACKAGE_DIR / name
                    if p != target:
                        shutil.copy2(p, target)
                        print(f"[build] 复制 {p} -> {target}")
                    return True, f"Zig 共享库构建成功: {target}"

        return False, (
            f"zig build 返回 0，但未在以下目录找到共享库: "
            f"{[str(d) for d in search_dirs]}"
        )

    except subprocess.TimeoutExpired:
        return False, "zig build 超时（180s）"
    except Exception as e:
        return False, f"zig build 异常: {e}"


def build_c_extensions(skip_zig: bool = False) -> Tuple[bool, str]:
    """构建 C 扩展（_renderer / _terminal）

    Returns:
        (success, message)
    """
    if not SETUP_PY.exists():
        return False, f"setup.py 不存在: {SETUP_PY}"

    cmd = [sys.executable, "setup.py", "build_ext", "--inplace"]
    if skip_zig:
        cmd.append("--skip-zig")

    print(f"[build] 执行: {' '.join(cmd)}")
    print(f"[build] 工作目录: {TUI_ROOT}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(TUI_ROOT),
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return False, (
                f"C 扩展构建失败 (code={result.returncode})\n"
                f"stdout: {result.stdout[-1000:]}\n"
                f"stderr: {result.stderr[-1000:]}"
            )
        return True, "C 扩展构建成功"
    except subprocess.TimeoutExpired:
        return False, "C 扩展构建超时（300s）"
    except Exception as e:
        return False, f"C 扩展构建异常: {e}"


# ============================================================================
# 产物验证
# ============================================================================
def verify_products() -> Dict[str, bool]:
    """验证构建产物

    Returns:
        {
            "c_renderer": bool,
            "c_terminal": bool,
            "zig_lib": bool,
            "renderer_import": bool,
            "terminal_import": bool,
            "zig_available": bool,
        }
    """
    plat = detect_platform()
    result = {
        "c_renderer_file": False,
        "c_terminal_file": False,
        "zig_lib_file": False,
        "renderer_import": False,
        "terminal_import": False,
        "zig_available": False,
    }

    # 文件存在性检查
    # C 扩展文件名带平台后缀（如 _renderer.cp312-win_amd64.pyd）
    # 简化：扫包目录下所有 _renderer.* 和 _terminal.*
    for pattern, key in [
        ("_renderer*", "c_renderer_file"),
        ("_terminal*", "c_terminal_file"),
    ]:
        for p in PACKAGE_DIR.glob(pattern):
            if p.suffix in (".pyd", ".so") and p.stem.startswith(("_renderer", "_terminal")):
                # 排除 _renderer.c 源码
                if p.suffix == ".c":
                    continue
                result[key] = True
                break

    # Zig 共享库
    lib_patterns = [
        f"zig_render{plat['lib_suffix']}",
        f"libzig_render{plat['lib_suffix']}",
    ]
    for name in lib_patterns:
        if (PACKAGE_DIR / name).exists():
            result["zig_lib_file"] = True
            break

    # 导入测试（在子进程中执行，避免污染当前进程）
    test_code = """
import sys
sys.path.insert(0, r'{pkg_dir}')

# _renderer 导入测试
try:
    from zeroai_tui import _renderer
    has_renderer = True
    has_zig = bool(_renderer.zig_available())
except Exception as e:
    has_renderer = False
    has_zig = False
    print(f"renderer import error: {{e}}", file=sys.stderr)

# _terminal 导入测试
try:
    from zeroai_tui import _terminal
    has_terminal = True
except Exception as e:
    has_terminal = False
    print(f"terminal import error: {{e}}", file=sys.stderr)

print(f"renderer_import={{has_renderer}}")
print(f"terminal_import={{has_terminal}}")
print(f"zig_available={{has_zig}}")
""".format(pkg_dir=str(TUI_ROOT))

    try:
        proc = subprocess.run(
            [sys.executable, "-c", test_code],
            cwd=str(TUI_ROOT),
            capture_output=True, text=True, timeout=15,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("renderer_import="):
                result["renderer_import"] = line.split("=", 1)[1] == "True"
            elif line.startswith("terminal_import="):
                result["terminal_import"] = line.split("=", 1)[1] == "True"
            elif line.startswith("zig_available="):
                result["zig_available"] = line.split("=", 1)[1] == "True"
    except Exception as e:
        print(f"[verify] 导入测试异常: {e}")

    return result


# ============================================================================
# 状态报告
# ============================================================================
def print_status_report(plat: Dict[str, str], verify: Dict[str, bool]) -> None:
    """打印状态报告"""
    print()
    print("=" * 60)
    print("ZeroAI TUI C/Zig 扩展构建报告")
    print("=" * 60)
    print(f"  系统: {plat['system']} {plat['machine']}")
    print(f"  Python: {plat['python_version']}")
    print(f"  共享库后缀: {plat['lib_suffix']}")
    print(f"  扩展后缀: {plat['ext_suffix']}")

    print()
    print("[环境检测]")
    zig = find_zig_executable()
    cc = find_c_compiler()
    print(f"  Zig: {zig or '未找到（可忽略）'}")
    print(f"  C 编译器: {cc or '未找到'}")

    print()
    print("[产物验证]")
    labels = {
        "c_renderer_file": "_renderer.{ext}",
        "c_terminal_file": "_terminal.{ext}",
        "zig_lib_file": "zig_render{lib}",
        "renderer_import": "_renderer 模块导入",
        "terminal_import": "_terminal 模块导入",
        "zig_available": "Zig 加速可用",
    }
    for key, label in labels.items():
        status = "OK" if verify.get(key) else "FAIL"
        mark = "[OK]  " if verify.get(key) else "[FAIL] "
        text = label.format(ext=plat['ext_suffix'], lib=plat['lib_suffix'])
        print(f"  {mark}{text}: {status}")

    print()
    print("[架构层级]")
    if verify.get("renderer_import"):
        if verify.get("zig_available"):
            print("  Python → C (_renderer) → Zig (zig_render)  [三层完整]")
        else:
            print("  Python → C (_renderer) → C 标量实现  [两层，Zig 降级]")
    else:
        print("  Python 纯实现  [C 扩展不可用，全部降级]")

    print("=" * 60)


# ============================================================================
# 主入口
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        prog="build_extensions",
        description="ZeroAI TUI C/Zig 扩展跨平台构建脚本",
    )
    parser.add_argument(
        "--skip-zig", action="store_true",
        help="跳过 Zig 构建（仅构建 C 扩展）",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="仅检查现状，不执行构建",
    )
    parser.add_argument(
        "--release", action="store_true", default=True,
        help="Release 模式构建（默认开启）",
    )
    args = parser.parse_args()

    plat = detect_platform()
    print(f"[build] 平台: {plat['system']} {plat['machine']}")
    print(f"[build] Python: {plat['python_version']}")

    if args.check_only:
        verify = verify_products()
        print_status_report(plat, verify)
        return 0 if verify.get("renderer_import") else 1

    # 1. 构建 Zig（失败不中断）
    print()
    print("-" * 60)
    print("[步骤 1/3] 构建 Zig 共享库")
    print("-" * 60)
    if args.skip_zig:
        print("[build] --skip-zig 已指定，跳过 Zig 构建")
        zig_ok, zig_msg = False, "已跳过"
    else:
        zig_ok, zig_msg = build_zig_library(release=args.release)
        print(f"[build] Zig: {zig_msg}")

    # 2. 构建 C 扩展（必须成功）
    print()
    print("-" * 60)
    print("[步骤 2/3] 构建 C 扩展")
    print("-" * 60)
    c_ok, c_msg = build_c_extensions(skip_zig=args.skip_zig)
    print(f"[build] C 扩展: {c_msg}")
    if not c_ok:
        print("[build] C 扩展构建失败，无法继续")
        return 1

    # 3. 产物验证
    print()
    print("-" * 60)
    print("[步骤 3/3] 产物验证")
    print("-" * 60)
    verify = verify_products()
    print_status_report(plat, verify)

    # 退出码：renderer 能导入即算成功
    return 0 if verify.get("renderer_import") else 1


if __name__ == "__main__":
    sys.exit(main())
