"""
Setup script for zeroai-tui C/Zig extensions

构建流程（严格按架构图）：
    1. 先调用 `zig build` 编译 Zig 共享库（zig_render.dll / libzig_render.so）
       - 失败则跳过，C 扩展仍可独立构建
    2. 再编译 C 扩展（_renderer.pyd / _terminal.pyd）
       - C 扩展运行时动态加载 Zig 库，编译期不依赖 Zig
    3. 安装产物：
       - zeroai_tui/_renderer.pyd  (C 扩展)
       - zeroai_tui/_terminal.pyd  (C 扩展)
       - zeroai_tui/zig_render.dll (Zig 共享库，由 build.zig 复制)

用法：
    python setup.py build_ext --inplace    # 开发期构建
    python setup.py install                # 安装
    python setup.py build_ext --inplace --skip-zig  # 跳过 Zig 构建（仅 C）
"""
import os
import shutil
import subprocess
import sys
from setuptools import setup, Extension

# ============================================================================
# 配置
# ============================================================================
HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.join(HERE, 'zeroai_tui')
SRC_DIR = os.path.join(PACKAGE_DIR, 'src')

# 是否跳过 Zig 构建（通过 --skip-zig 参数控制）
SKIP_ZIG = '--skip-zig' in sys.argv
if SKIP_ZIG:
    sys.argv.remove('--skip-zig')


# ============================================================================
# 第1步：构建 Zig 共享库
# ============================================================================
def find_zig_executable() -> str:
    """查找 zig 可执行文件路径

    优先从 PATH 查找，再搜索常见安装路径。
    """
    # 1. PATH 中查找
    zig_in_path = shutil.which('zig')
    if zig_in_path:
        return zig_in_path

    # 2. 常见安装路径（Windows）
    common_paths = [
        r'C:\zig\zig.exe',
        r'C:\Program Files\Zig\zig.exe',
        r'C:\Program Files (x86)\Zig\zig.exe',
    ]
    for path in common_paths:
        if os.path.isfile(path):
            return path

    return 'zig'


def build_zig_library():
    """调用 zig build 编译 Zig 共享库

    构建产物由 build.zig 自动复制到 zeroai_tui/ 目录。
    失败时返回 False，C 扩展仍可独立构建（运行时自动回退）。
    """
    if SKIP_ZIG:
        print("[setup] --skip-zig specified, skipping Zig build")
        return False

    zig_exe = find_zig_executable()

    # 检查 zig 是否可用
    try:
        result = subprocess.run(
            [zig_exe, 'version'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            print("[setup] zig not available, skipping Zig build")
            return False
        zig_version = result.stdout.strip()
        print(f"[setup] Found zig {zig_version}, building Zig library...")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("[setup] zig not found in PATH, skipping Zig build")
        return False
    except Exception as e:
        print(f"[setup] zig check failed: {e}, skipping Zig build")
        return False

    # 检查 build.zig 是否存在
    build_zig_path = os.path.join(HERE, 'build.zig')
    if not os.path.exists(build_zig_path):
        print(f"[setup] build.zig not found at {build_zig_path}, skipping Zig build")
        return False

    # 调用 zig build
    try:
        result = subprocess.run(
            [zig_exe, 'build', '-Doptimize=ReleaseFast'],
            cwd=HERE,
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f"[setup] zig build failed (returncode={result.returncode})")
            if result.stdout:
                print(f"[setup] zig stdout: {result.stdout[:500]}")
            if result.stderr:
                print(f"[setup] zig stderr: {result.stderr[:500]}")
            return False

        print("[setup] zig build succeeded")

        # 验证产物存在（支持 build.zig 输出到不同路径）
        lib_names = ['zig_render.dll', 'libzig_render.so', 'libzig_render.dylib']
        search_dirs = [
            PACKAGE_DIR,
            os.path.join(HERE, 'zig-out', 'zeroai_tui'),
            os.path.join(HERE, 'zig-out', 'bin'),
            os.path.join(HERE, 'zig-out', 'lib'),
            os.path.join(HERE, 'zig-out'),
        ]

        for name in lib_names:
            for search_dir in search_dirs:
                src_path = os.path.join(search_dir, name)
                if os.path.exists(src_path):
                    dest_path = os.path.join(PACKAGE_DIR, name)
                    if src_path != dest_path:
                        shutil.copy2(src_path, dest_path)
                        print(f"[setup] Copied Zig library: {src_path} -> {dest_path}")
                    else:
                        print(f"[setup] Zig library installed: {src_path}")
                    return True

        print(f"[setup] zig build succeeded but library not found in searched dirs")
        return False
    except subprocess.TimeoutExpired:
        print("[setup] zig build timed out (120s), skipping")
        return False
    except Exception as e:
        print(f"[setup] zig build error: {e}")
        return False


# 构建 Zig 库（失败不中断，C 扩展仍可独立构建）
_zig_built = build_zig_library()


# ============================================================================
# 第2步：定义 C 扩展
# ============================================================================

# 检测 Python 头文件版本是否匹配
# 如果 TRAE 等嵌入式环境的头文件版本与实际 Python 版本不一致，
# 可通过环境变量 ZEROAI_PYTHON_INCLUDE_DIR 指定匹配的头文件目录
import sysconfig

def _get_python_include_dirs():
    """获取 Python 头文件目录，支持版本匹配覆盖"""
    default_inc = sysconfig.get_path('include')
    env_inc = os.environ.get('ZEROAI_PYTHON_INCLUDE_DIR')
    if env_inc and os.path.isdir(env_inc):
        # 验证头文件版本
        patchlevel = os.path.join(env_inc, 'patchlevel.h')
        if os.path.exists(patchlevel):
            try:
                with open(patchlevel, 'r', encoding='utf-8') as f:
                    for line in f:
                        if 'PY_VERSION' in line and '"' in line:
                            ver = line.split('"')[1]
                            actual_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
                            if ver == actual_ver:
                                print(f"[setup] Using matched Python headers: {env_inc} (v{ver})")
                                return [env_inc]
                            else:
                                print(f"[setup] WARNING: Header version {ver} != Python {actual_ver}")
                                break
            except Exception:
                pass
    return [default_inc]

def _get_python_library_dirs():
    """获取 Python 库文件目录"""
    default_lib = sysconfig.get_config_var('LIBDIR') or os.path.join(sys.prefix, 'libs')
    env_lib = os.environ.get('ZEROAI_PYTHON_LIB_DIR')
    if env_lib and os.path.isdir(env_lib):
        return [env_lib, default_lib]
    return [default_lib]

def _get_python_libraries():
    """获取要链接的 Python 库列表

    在 TRAE 等嵌入式环境中，默认的 python3.lib 可能指向错误版本的 DLL
    （如 python312.dll 而非 python310.dll）。此时通过环境变量
    ZEROAI_PYTHON_LIB_DIR 指定包含正确 python310.lib 的目录，
    并强制链接 python310.lib。
    """
    if os.name == 'nt':
        env_lib = os.environ.get('ZEROAI_PYTHON_LIB_DIR')
        if env_lib and os.path.isdir(env_lib):
            # 检查是否存在 python310.lib（或对应版本的 lib）
            py_ver_nodot = f"{sys.version_info.major}{sys.version_info.minor}"
            candidate_lib = os.path.join(env_lib, f"python{py_ver_nodot}.lib")
            if os.path.exists(candidate_lib):
                print(f"[setup] Using matched Python library: python{py_ver_nodot}.lib")
                return [f"python{py_ver_nodot}"]
    return None  # None 表示使用默认行为

include_dirs = _get_python_include_dirs()
library_dirs = _get_python_library_dirs()
libraries = _get_python_libraries()
print(f"[setup] include_dirs: {include_dirs}")
print(f"[setup] library_dirs: {library_dirs}")
print(f"[setup] libraries: {libraries}")

extensions = []

# _renderer extension（C 扩展，运行时动态加载 Zig）
renderer_src = os.path.join(SRC_DIR, '_renderer.c')
if os.path.exists(renderer_src):
    compile_args = ['/O2', '/GL'] if os.name == 'nt' else ['-O3', '-fPIC']
    # Linux/macOS 需要 -ldl 用于 dlopen/dlsym 动态加载
    link_args = ['/LTCG'] if os.name == 'nt' else ['-ldl']

    ext_kwargs = dict(
        sources=[renderer_src],
        extra_compile_args=compile_args,
        extra_link_args=link_args,
        include_dirs=include_dirs,
        library_dirs=library_dirs,
    )
    if libraries:
        ext_kwargs['libraries'] = libraries

    extensions.append(
        Extension('zeroai_tui._renderer', **ext_kwargs)
    )
else:
    print(f"[setup] WARNING: {renderer_src} not found")

# _terminal extension
terminal_src = os.path.join(SRC_DIR, '_terminal.c')
if os.path.exists(terminal_src):
    compile_args = ['/O2', '/GL'] if os.name == 'nt' else ['-O3', '-fPIC']
    link_args = ['/LTCG'] if os.name == 'nt' else []

    ext_kwargs = dict(
        sources=[terminal_src],
        extra_compile_args=compile_args,
        extra_link_args=link_args,
        include_dirs=include_dirs,
        library_dirs=library_dirs,
    )
    if libraries:
        ext_kwargs['libraries'] = libraries

    extensions.append(
        Extension('zeroai_tui._terminal', **ext_kwargs)
    )
else:
    print(f"[setup] WARNING: {terminal_src} not found")


# ============================================================================
# 第3步：setup
# ============================================================================
setup(
    name='zeroai-tui',
    version='0.3.0',
    description='ZeroAI TUI Framework with C/Zig acceleration',
    packages=['zeroai_tui'],
    package_data={
        'zeroai_tui': [
            # 包含 Zig 共享库（如果构建成功）
            'zig_render.dll', 'libzig_render.so', 'libzig_render.dylib',
        ],
    },
    ext_modules=extensions,
    python_requires='>=3.10',
)

# 打印构建摘要
print("\n[setup] Build summary:")
print(f"  Zig library built: {_zig_built}")
print(f"  C extensions: {len(extensions)}")
for ext in extensions:
    print(f"    - {ext.name}")
print(f"  Architecture: Python -> C -> Zig (with automatic fallback)")
