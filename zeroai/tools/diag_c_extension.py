"""C 扩展构建环境诊断与修复（阶段 H.1）

诊断 Python.h 头文件是否可用，提供修复方案。

问题根因：
    TRAE 内置 Python 是嵌入式版本，不包含 Include/ 头文件和 libs/ 库文件。
    C 扩展编译需要 Python.h 和 python3xx.lib。

修复方案：
    1. 下载官方 Python 安装器（与当前 Python 版本完全匹配）
    2. 选择 "Customize installation" → 勾选 "Download debugging symbols" 和 "Install for all users"
    3. 安装后将其 Include/ 和 libs/ 复制到 TRAE Python 目录

    或：
    1. 从 python.org 下载对应版本的源码包
    2. 提取 Include/ 目录到 TRAE Python 目录
    3. 从安装器提取 libs/ 目录

使用方式：
    python -m zeroai.tools.diag_c_extension
"""
from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


def diagnose_python_env() -> Dict[str, Any]:
    """诊断 Python 开发环境

    Returns:
        诊断报告字典
    """
    report: Dict[str, Any] = {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "python_prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "include_path": sysconfig.get_path("include"),
        "platinclude_path": sysconfig.get_path("platinclude"),
        "include_exists": False,
        "python_h_exists": False,
        "libs_path": "",
        "libs_exists": False,
        "lib_file": "",
        "platform": sys.platform,
        "arch": sys.maxsize > 2**32 and "64-bit" or "32-bit",
        "issues": [],
        "solutions": [],
    }

    # 检查 Include 目录
    include_path = Path(report["include_path"])
    report["include_exists"] = include_path.exists()
    if report["include_exists"]:
        python_h = include_path / "Python.h"
        report["python_h_exists"] = python_h.exists()
        if not report["python_h_exists"]:
            report["issues"].append("Python.h 头文件缺失")
    else:
        report["issues"].append(f"Include 目录不存在: {include_path}")

    # 检查 libs 目录（Windows）
    if sys.platform == "win32":
        libs_path = Path(sys.prefix) / "libs"
        report["libs_path"] = str(libs_path)
        report["libs_exists"] = libs_path.exists()
        if report["libs_exists"]:
            # 查找 python3xx.lib
            version_nodot = f"{sys.version_info.major}{sys.version_info.minor}"
            lib_file = libs_path / f"python{version_nodot}.lib"
            report["lib_file"] = str(lib_file)
            if not lib_file.exists():
                report["issues"].append(f"python{version_nodot}.lib 库文件缺失")
        else:
            report["issues"].append(f"libs 目录不存在: {libs_path}")

    # 生成解决方案
    if report["issues"]:
        report["solutions"] = _generate_solutions(report)

    return report


def _generate_solutions(report: Dict[str, Any]) -> list:
    """生成修复方案"""
    solutions = []
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    arch = "amd64" if report["arch"] == "64-bit" else "win32"

    solutions.append({
        "method": "download_installer",
        "title": f"下载 Python {version} 官方安装器",
        "url": f"https://www.python.org/downloads/release/python-{version.replace('.', '')}/",
        "steps": [
            f"1. 访问 https://www.python.org/downloads/release/python-{version.replace('.', '_')}/",
            f"2. 下载 Windows installer (64-bit)（当前版本 {version}）",
            "3. 运行安装器，选择 'Customize installation'",
            "4. 勾选 'tcl/tk and IDLE'、'py launcher'、'for all users'",
            "5. Advanced Options → 勾选 'Download debugging symbols'",
            f"6. 安装到默认路径（如 C:\\Python{version_nodot()}）",
            f"7. 复制 <安装路径>\\Include 到 {report['include_path']}",
            "8. 复制 <安装路径>\\libs 到 {report.get('libs_path', '<prefix>\\libs')}",
        ],
    })

    solutions.append({
        "method": "embedded_package",
        "title": "从嵌入式包提取",
        "steps": [
            f"1. 下载 python-{version}-embed-{arch}.zip",
            "2. 解压后复制 python3xx.dll 到 TRAE Python 目录",
            "3. 注意：嵌入式包不含 Python.h，需配合方案 1",
        ],
    })

    solutions.append({
        "method": "system_python",
        "title": "使用系统 Python",
        "steps": [
            "1. 安装完整版 Python 到系统",
            "2. 使用系统 Python 创建虚拟环境: python -m venv venv",
            "3. 激活虚拟环境后安装 zeroai: pip install -e .",
            "4. 用虚拟环境的 Python 编译 C 扩展",
        ],
    })

    return solutions


def version_nodot() -> str:
    """返回无点的版本号（如 310）"""
    return f"{sys.version_info.major}{sys.version_info.minor}"


def try_auto_fix() -> Tuple[bool, str]:
    """尝试自动修复（从其他 Python 安装复制头文件）

    Returns:
        (成功标志, 消息)
    """
    # 搜索系统上其他 Python 安装
    candidate_paths = []

    current_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    current_version_nodot = version_nodot()

    if sys.platform == "win32":
        # 常见安装路径
        candidates = [
            f"C:\\Python{current_version_nodot}\\Include",
            f"C:\\Python{current_version_nodot}-x64\\Include",
            f"C:\\Program Files\\Python{current_version_nodot}\\Include",
            f"C:\\Program Files (x86)\\Python{current_version_nodot}\\Include",
            f"C:\\Users\\{os.environ.get('USERNAME', '')}\\AppData\\Local\\Programs\\Python\\Python{current_version_nodot}\\Include",
        ]
        for c in candidates:
            if Path(c).exists() and (Path(c) / "Python.h").exists():
                candidate_paths.append(c)

    # 检查 PATH 中的其他 python（验证版本匹配）
    try:
        result = subprocess.run(
            ["where", "python"] if sys.platform == "win32" else ["which", "-a", "python"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line or line == sys.executable:
                continue
            # 验证版本匹配
            try:
                ver_result = subprocess.run(
                    [line, "--version"],
                    capture_output=True, text=True, timeout=5
                )
                ver_str = ver_result.stdout.strip() or ver_result.stderr.strip()
                if current_version not in ver_str:
                    continue  # 版本不匹配，跳过
            except Exception:
                continue

            # 推断 Include 路径
            py_dir = Path(line).parent
            include_dir = py_dir / "Include"
            if not include_dir.exists():
                include_dir = py_dir.parent / "Include"
            if include_dir.exists() and (include_dir / "Python.h").exists():
                candidate_paths.append(str(include_dir))
    except Exception:
        pass

    if not candidate_paths:
        return False, f"未找到 Python {current_version} 的头文件来源（系统上的其他 Python 版本不匹配）"

    # 从第一个候选路径复制
    import shutil
    src_include = Path(candidate_paths[0])
    dst_include = Path(sysconfig.get_path("include"))
    dst_include.mkdir(parents=True, exist_ok=True)

    # 复制所有 .h 文件和 cpython/ 子目录
    copied = 0
    for item in src_include.iterdir():
        try:
            if item.is_file() and item.suffix == ".h":
                shutil.copy2(item, dst_include / item.name)
                copied += 1
            elif item.is_dir():
                dst_subdir = dst_include / item.name
                if dst_subdir.exists():
                    shutil.rmtree(dst_subdir)
                shutil.copytree(item, dst_subdir)
                copied += len(list(item.glob("*.h")))
        except Exception:
            pass

    if copied > 0:
        # 同时复制 libs（Windows）
        if sys.platform == "win32":
            src_libs = src_include.parent / "libs"
            dst_libs = Path(sys.prefix) / "libs"
            if src_libs.exists():
                dst_libs.mkdir(parents=True, exist_ok=True)
                for f in src_libs.glob("*.lib"):
                    try:
                        shutil.copy2(f, dst_libs / f.name)
                    except Exception:
                        pass
        return True, f"已复制 {copied} 个头文件到 {dst_include}（版本匹配 {current_version}）"

    return False, "复制头文件失败"


def print_diagnostic_report() -> None:
    """打印诊断报告"""
    report = diagnose_python_env()

    print("=" * 60)
    print("C 扩展构建环境诊断报告")
    print("=" * 60)
    print()

    print(f"Python 版本: {report['python_version'].split()[0]}")
    print(f"Python 路径: {report['python_executable']}")
    print(f"安装前缀:   {report['python_prefix']}")
    print(f"基础前缀:   {report['base_prefix']}")
    print(f"架构:       {report['arch']}")
    print(f"平台:       {report['platform']}")
    print()

    print("头文件检查:")
    print(f"  Include 路径: {report['include_path']}")
    print(f"  目录存在:     {'是' if report['include_exists'] else '否'}")
    print(f"  Python.h:     {'存在' if report['python_h_exists'] else '缺失'}")
    print()

    if sys.platform == "win32":
        print("库文件检查:")
        print(f"  libs 路径:    {report['libs_path']}")
        print(f"  目录存在:     {'是' if report['libs_exists'] else '否'}")
        if report['lib_file']:
            print(f"  lib 文件:     {report['lib_file']}")
        print()

    if report["issues"]:
        print("=" * 60)
        print(f"发现问题 ({len(report['issues'])} 项):")
        print("=" * 60)
        for i, issue in enumerate(report["issues"], 1):
            print(f"  {i}. {issue}")
        print()

        print("=" * 60)
        print("修复方案:")
        print("=" * 60)
        for sol in report["solutions"]:
            print(f"\n  方案: {sol['title']}")
            if "url" in sol:
                print(f"  URL:  {sol['url']}")
            for step in sol.get("steps", []):
                print(f"    {step}")

        # 尝试自动修复
        print()
        print("=" * 60)
        print("尝试自动修复...")
        print("=" * 60)
        success, msg = try_auto_fix()
        if success:
            print(f"\n  [成功] {msg}")
            print("  请重新运行 C 扩展构建")
        else:
            print(f"\n  [跳过] {msg}")
            print("  请按上述方案手动修复")
    else:
        print("=" * 60)
        print("[OK] C 扩展构建环境完整")
        print("=" * 60)
        print("可以运行: python setup.py build_ext --inplace")


if __name__ == "__main__":
    print_diagnostic_report()


__all__ = [
    "diagnose_python_env",
    "try_auto_fix",
    "print_diagnostic_report",
]
