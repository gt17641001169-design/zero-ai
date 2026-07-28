"""文件管理工具

迁移来源：tui_agent.py 行 1760-1834, 2725-2749, 3094-3162, 3213-3262, 3388-3443

提供以下纯函数：
- auto_backup：全权限模式下修改/删除核心文件前自动备份
- read_file：读取文件内容（多编码兼容）
- write_file：写入文件
- list_dir：列出目录内容（支持树形递归）
- search_files：在文件内容中搜索正则
- delete_file：删除文件（全权限模式下核心文件自动备份）
- move_file：移动文件
- copy_file：复制文件
- create_dir：创建目录
- edit_file：按行编辑文件（替换/插入/删除/追加）
- file_diff：比较两个文件差异
- read_image：读取图片为 base64 data URI

依赖：
- zeroai.core.runtime：runtime_cache（备份目录基于运行时缓存）
- zeroai.core.constants：PERMISSION_LEVEL, MAX_FILE_SIZE
- zeroai.core.paths：ICONS_DIR（用于 _load_svg_icon）
"""
import os
import re
import shutil
from pathlib import Path

from zeroai.core.runtime import runtime_cache
from zeroai.core.constants import PERMISSION_LEVEL, MAX_FILE_SIZE
from zeroai.core.paths import ICONS_DIR


# 备份目录（使用运行时缓存，程序退出自动删除，不再污染工作目录）
BACKUP_DIR = str(runtime_cache.cache_dir / "backups")
os.makedirs(BACKUP_DIR, exist_ok=True) if PERMISSION_LEVEL == "full" else None

# 核心文件清单（修改前自动备份）
CORE_FILES = {
    "tui_agent.py", "settings.json", "requirements.txt", "README.md",
    "config.py", "tools.py", "prompts.py", "utils.py", "main.py",
}


def _load_svg_icon(name: str) -> str:
    """加载 SVG 图标文件内容，返回纯文本标签（终端无法渲染 SVG，返回文字标签）

    迁移来源：tui_agent.py 行 251-270
    """
    svg_path = ICONS_DIR / f"{name}.svg"
    if svg_path.exists():
        # 终端环境下返回对应的文字标签
        ICON_LABELS = {
            "folder": "[DIR]",
            "file": "[FILE]",
            "search": "[SCAN]",
            "check": "[OK]",
            "cross": "[ERR]",
            "warning": "[!]",
            "security": "[SEC]",
            "monitor": "[SCREEN]",
            "download": "[DL]",
            "document": "[DOC]",
            "tool": "[TOOL]",
        }
        return ICON_LABELS.get(name, "")
    return ""


def auto_backup(file_path: str) -> str:
    """全权限模式下，修改/删除核心文件前自动备份
    返回备份路径，失败返回错误信息

    迁移来源：tui_agent.py 行 1759-1780
    """
    if PERMISSION_LEVEL != "full":
        return ""
    try:
        full = Path(file_path).resolve()
        if not full.exists():
            return ""
        # 只备份核心文件
        if full.name not in CORE_FILES:
            return ""
        # 生成备份文件名：原名.时间戳.bak
        import time
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"{full.name}.{ts}.bak"
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        shutil.copy2(str(full), backup_path)
        return backup_path
    except Exception as e:
        return f"备份失败：{e}"


def read_file(path: str, max_length: int = 3000) -> str:
    """读取文件内容（多编码兼容）

    迁移来源：tui_agent.py 行 1802-1821
    """
    try:
        full = Path(path).resolve()
        if not full.exists():
            return f"错误：文件不存在 {path}"
        if full.is_dir():
            return f"错误：{path} 是目录"
        if full.stat().st_size > MAX_FILE_SIZE:
            return "错误：文件太大"
        for enc in ["utf-8", "gbk", "latin-1"]:
            try:
                text = full.read_text(encoding=enc)
                if len(text) > max_length:
                    text = text[:max_length] + f"\n... [已截断，共{len(text)}字符，显示前{max_length}字符]"
                return text
            except UnicodeDecodeError:
                continue
        return "错误：无法解码"
    except Exception as e:
        return f"错误：{e}"


def write_file(path: str, content: str) -> str:
    """写入文件

    迁移来源：tui_agent.py 行 1824-1831
    """
    try:
        full = Path(path).resolve()
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return f"已写入 {len(content)} 字符到 {path}"
    except Exception as e:
        return f"错误：{e}"


def list_dir(path: str = ".", recursive: bool = False, max_depth: int = 15) -> str:
    """列出目录内容
    path: 目录路径
    recursive: 是否递归显示子目录（树形结构）
    max_depth: 递归最大深度（1=只看当前层，默认15=深入最深层，自动跳过无权限目录）

    迁移来源：tui_agent.py 行 1834-1916
    """
    try:
        full = Path(path).resolve()
        if not full.exists() or not full.is_dir():
            return f"错误：目录不存在 {path}"

        # 忽略的目录（避免扫描无用内容）
        IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
                       ".idea", ".vs", "dist", "build", ".next", ".nuxt",
                       "target", ".gradle", ".mypy_cache", ".pytest_cache",
                       ".cache", ".npm", ".yarn", "bower_components", "vendor"}

        if not recursive:
            # 原有行为：只显示一层
            items = []
            dir_tag = _load_svg_icon("folder")
            file_tag = _load_svg_icon("file")
            for p in sorted(full.iterdir()):
                tag = dir_tag if p.is_dir() else file_tag
                size = p.stat().st_size if p.is_file() else ""
                items.append(f"{tag} {p.name} {size}")
            return "\n".join(items) if items else "(空目录)"

        # 递归模式：树形结构（深入最深层）
        lines = []
        file_count = 0
        dir_count = 0
        max_files = 500  # 安全上限，避免超大目录卡死模型（500足够了解结构）

        def _walk(directory: Path, prefix: str, depth: int):
            nonlocal file_count, dir_count
            if depth > max_depth or file_count >= max_files:
                return
            try:
                entries = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except (PermissionError, OSError):
                return  # 无权限目录自动跳过

            # 过滤忽略目录
            entries = [e for e in entries if e.name not in IGNORE_DIRS]

            for idx, entry in enumerate(entries):
                if file_count >= max_files:
                    lines.append(f"{prefix}... (已达到最大文件数 {max_files}，停止扫描)")
                    return
                is_last = (idx == len(entries) - 1)
                connector = "└── " if is_last else "├── "

                if entry.is_dir():
                    dir_count += 1
                    lines.append(f"{prefix}{connector}{entry.name}/")
                    # 递归子目录（深入最深层）
                    extension = "    " if is_last else "│   "
                    _walk(entry, prefix + extension, depth + 1)
                else:
                    file_count += 1
                    try:
                        size = entry.stat().st_size
                        size_str = f" ({_format_size(size)})" if size > 0 else ""
                    except OSError:
                        size_str = ""
                    lines.append(f"{prefix}{connector}{entry.name}{size_str}")

        def _format_size(size: int) -> str:
            if size < 1024:
                return f"{size}B"
            elif size < 1024 * 1024:
                return f"{size/1024:.1f}KB"
            else:
                return f"{size/1024/1024:.1f}MB"

        lines.append(f"{full.name}/")
        _walk(full, "", 1)
        lines.append(f"\n共 {dir_count} 个目录，{file_count} 个文件"
                    + (f"（已达上限 {max_files}，可能未扫描完）" if file_count >= max_files else ""))
        return "\n".join(lines)
    except Exception as e:
        return f"错误：{e}"


def search_files(pattern: str, path: str = ".") -> str:
    """在文件内容中搜索正则

    迁移来源：tui_agent.py 行 2725-2749

    全权限模式：无深度限制、结果数扩大到 200
    受限模式：跳过常见二进制，结果数限制 50
    """
    try:
        results = []
        # 全权限：跳过二进制过滤（仍跳过目录）；受限：也跳过常见二进制
        skip_suffixes = [".exe", ".dll", ".zip", ".pyc"] if PERMISSION_LEVEL == "full" else [".exe", ".dll", ".png", ".jpg", ".zip", ".pyc"]
        # 全权限：结果数限制 200；受限：50
        max_results = 200 if PERMISSION_LEVEL == "full" else 50
        for p in Path(path).rglob("*"):
            if p.is_dir() or p.suffix.lower() in skip_suffixes:
                continue
            if p.stat().st_size > MAX_FILE_SIZE:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(content.splitlines(), 1):
                    if re.search(pattern, line):
                        results.append(f"{p.name}:{i}: {line.strip()}")
                        if len(results) >= max_results:
                            return "\n".join(results) + f"\n...(截断至 {max_results} 条)"
            except Exception:
                continue
        return "\n".join(results) if results else "(无匹配)"
    except Exception as e:
        return f"错误：{e}"


def delete_file(path: str) -> str:
    """全权限模式：直接删除核心文件前自动备份

    迁移来源：tui_agent.py 行 3094-3127
    """
    try:
        full = Path(path).resolve()
        if not full.exists():
            return f"错误：文件不存在 {path}"
        # 国家级项目硬约束：删除核心文件前自动备份
        backup_info = ""
        if PERMISSION_LEVEL == "full" and full.name in CORE_FILES:
            backup_path = auto_backup(str(full))
            if backup_path and not backup_path.startswith("备份失败"):
                backup_info = f"\n[已备份] {backup_path}"
        # 优先用 send2trash 软删除，全权限模式下直接删除
        if PERMISSION_LEVEL == "full":
            # 全权限：直接删除（不可恢复，但有备份）
            if full.is_dir():
                shutil.rmtree(str(full))
            else:
                full.unlink()
            return f"{_load_svg_icon('cross')} 已删除：{path}{backup_info}"
        else:
            # 受限模式：移入回收站
            try:
                from send2trash import send2trash
                send2trash(str(full))
                return f"已移入回收站：{path}"
            except ImportError:
                if full.is_dir():
                    shutil.rmtree(str(full))
                else:
                    full.unlink()
                return f"{_load_svg_icon('cross')} 已删除：{path}"
    except Exception as e:
        return f"错误：{e}"


def move_file(src: str, dst: str) -> str:
    """移动文件

    迁移来源：tui_agent.py 行 3130-3138
    """
    try:
        s = Path(src).resolve()
        if not s.exists():
            return f"错误：源文件不存在 {src}"
        shutil.move(str(s), str(Path(dst).resolve()))
        return f"{_load_svg_icon('check')} 已移动：{src} → {dst}"
    except Exception as e:
        return f"错误：{e}"


def copy_file(src: str, dst: str) -> str:
    """复制文件

    迁移来源：tui_agent.py 行 3141-3151
    """
    try:
        s = Path(src).resolve()
        if not s.exists():
            return f"错误：源文件不存在 {src}"
        d = Path(dst).resolve()
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(s), str(d))
        return f"{_load_svg_icon('check')} 已复制：{src} → {dst}"
    except Exception as e:
        return f"错误：{e}"


def create_dir(path: str) -> str:
    """创建目录

    迁移来源：tui_agent.py 行 3154-3160
    """
    try:
        full = Path(path).resolve()
        full.mkdir(parents=True, exist_ok=True)
        return f"已创建目录：{path}"
    except Exception as e:
        return f"错误：{e}"


def edit_file(path: str, operation: str = "replace", line: int = 1, content: str = "", start_line: int = 0, end_line: int = 0) -> str:
    """按行编辑文件：替换/插入/删除指定行

    迁移来源：tui_agent.py 行 3213-3260
    """
    try:
        full = Path(path).resolve()
        if not full.exists():
            return f"错误：文件不存在 {path}"
        if full.is_dir():
            return f"错误：{path} 是目录"
        for enc in ["utf-8", "gbk", "latin-1"]:
            try:
                text = full.read_text(encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return "错误：无法解码"
        lines = text.splitlines(keepends=True)
        total = len(lines)
        if operation == "replace":
            if line < 1 or line > total:
                return f"错误：行号 {line} 超出范围（1-{total}）"
            old = lines[line - 1].rstrip("\n\r")
            lines[line - 1] = content + "\n"
            full.write_text("".join(lines), encoding=enc)
            return f"{_load_svg_icon('check')} 第{line}行已替换\n  原内容：{old}\n  新内容：{content}"
        elif operation == "insert":
            if line < 1 or line > total + 1:
                return f"错误：行号 {line} 超出范围（1-{total+1}）"
            lines.insert(line - 1, content + "\n")
            full.write_text("".join(lines), encoding=enc)
            return f"{_load_svg_icon('check')} 已在第{line}行插入：{content}"
        elif operation == "delete":
            s = start_line or line
            e = end_line or line
            if s < 1 or e > total or s > e:
                return f"错误：行范围 {s}-{e} 无效（1-{total}）"
            deleted = lines[s - 1:e]
            del lines[s - 1:e]
            full.write_text("".join(lines), encoding=enc)
            return f"{_load_svg_icon('cross')} 已删除第{s}-{e}行（共{len(deleted)}行）"
        elif operation == "append":
            lines.append(content + "\n")
            full.write_text("".join(lines), encoding=enc)
            return f"{_load_svg_icon('check')} 已在末尾追加：{content}"
        else:
            return f"错误：未知操作 {operation}，支持 replace/insert/delete/append"
    except Exception as e:
        return f"错误：{e}"


def file_diff(path_a: str, path_b: str) -> str:
    """比较两个文件差异

    迁移来源：tui_agent.py 行 3388-3405
    """
    import difflib
    try:
        a = Path(path_a).resolve()
        b = Path(path_b).resolve()
        if not a.exists():
            return f"错误：文件不存在 {path_a}"
        if not b.exists():
            return f"错误：文件不存在 {path_b}"
        text_a = a.read_text(encoding="utf-8", errors="replace").splitlines()
        text_b = b.read_text(encoding="utf-8", errors="replace").splitlines()
        diff = list(difflib.unified_diff(text_a, text_b, fromfile=path_a, tofile=path_b, lineterm=""))
        if not diff:
            return "两个文件内容完全相同"
        return "\n".join(diff[:200])
    except Exception as e:
        return f"错误：{e}"


def read_image(path: str) -> str:
    """读取图片文件，返回 base64 编码（用于多模态消息）

    迁移来源：tui_agent.py 行 3408-3441
    """
    try:
        import base64 as b64
        full = Path(path).resolve()
        if not full.exists():
            return f"错误：图片不存在 {path}"
        ext = full.suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            return f"错误：不支持的图片格式 {ext}，支持 png/jpg/jpeg/gif/bmp/webp"
        if full.stat().st_size > 10 * 1024 * 1024:
            return "错误：图片太大（超过10MB）"
        # 压缩大图：超过 1MB 的图片缩放到 1920px 宽
        data = full.read_bytes()
        if full.stat().st_size > 1024 * 1024:
            try:
                from PIL import Image
                import io
                img = Image.open(full)
                if img.width > 1920:
                    ratio = 1920 / img.width
                    img = img.resize((1920, int(img.height * ratio)), Image.LANCZOS)
                buf = io.BytesIO()
                fmt = "PNG" if ext == ".png" else "JPEG"
                img.save(buf, format=fmt, quality=85)
                data = buf.getvalue()
            except Exception:
                pass  # 压缩失败就用原图
        b64_data = b64.b64encode(data).decode("ascii")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "bmp": "image/bmp", "webp": "image/webp"}.get(ext.lstrip("."), "image/png")
        return f"data:{mime};base64,{b64_data}"
    except Exception as e:
        return f"错误：{e}"
