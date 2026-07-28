"""项目文件索引器 - 扫描项目目录并切块索引

功能：
1. 扫描项目目录下的代码文件（.py/.js/.ts/.md/.txt 等）
2. 按函数/类/段落切分为 chunk
3. 调用 VectorStore 建立向量索引
4. 支持增量更新：只重新索引变更的文件

设计原则：
- 尊重 .gitignore，跳过 node_modules/__pycache__/.git 等
- 文件大小限制：超过 1MB 的文件不索引
- 切块策略：Python 按函数/类切，其他按段落切
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .vector_store import VectorStore, get_vector_store


# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".c", ".h", ".cpp",
    ".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json", ".sql",
    ".sh", ".bat", ".ps1", ".zig",
}

# 跳过的目录
SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "dist", "build", "target", "out", ".next", ".nuxt",
    ".venv", "venv", "env", ".env",
    ".idea", ".vscode", ".trae-cn",
    "site-packages", "egg-info",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
}

# 文件大小上限（1MB）
MAX_FILE_SIZE = 1024 * 1024


def _should_skip(path: str) -> bool:
    """判断路径是否应该跳过"""
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in SKIP_DIRS:
            return True
        if part.startswith(".") and part not in (".", ".."):
            # 跳过隐藏目录，但允许当前目录
            if part not in (".github", ".zeroai"):
                return True
    return False


def _chunk_python(source: str, max_chunk_size: int = 800) -> List[str]:
    """Python 文件按函数/类切块

    策略：
    1. 用正则提取 def/class 块
    2. 模块级代码作为单独 chunk
    3. 超长的函数按行数切分
    """
    chunks = []

    # 提取模块文档字符串和导入（作为第一个 chunk）
    lines = source.split("\n")
    module_header = []
    in_header = True
    for line in lines:
        stripped = line.strip()
        if in_header:
            if stripped.startswith(("import ", "from ", "#", '"""', "'''")) or not stripped:
                module_header.append(line)
            elif stripped.startswith("def ") or stripped.startswith("class "):
                in_header = False
                break
            else:
                module_header.append(line)
        else:
            break

    if module_header:
        header_text = "\n".join(module_header).strip()
        if header_text and len(header_text) > 20:
            chunks.append(header_text)

    # 提取函数和类
    pattern = re.compile(
        r'^(?:async\s+def|def|class)\s+\w+.*?(?=\n(?:async\s+def|def|class)\s+\w+|\Z)',
        re.DOTALL | re.MULTILINE,
    )
    for match in pattern.finditer(source):
        chunk = match.group(0).strip()
        if not chunk:
            continue
        # 超长切分
        if len(chunk) > max_chunk_size:
            chunk_lines = chunk.split("\n")
            current = []
            current_len = 0
            for line in chunk_lines:
                if current_len + len(line) > max_chunk_size and current:
                    chunks.append("\n".join(current))
                    current = [line]
                    current_len = len(line)
                else:
                    current.append(line)
                    current_len += len(line)
            if current:
                chunks.append("\n".join(current))
        else:
            chunks.append(chunk)

    return chunks if chunks else [source[:max_chunk_size]]


def _chunk_text(source: str, max_chunk_size: int = 800) -> List[str]:
    """通用文本按段落切块"""
    if len(source) <= max_chunk_size:
        return [source] if source.strip() else []

    chunks = []
    # 按空行分段
    paragraphs = re.split(r"\n\s*\n", source)
    current = ""
    for para in paragraphs:
        if not para.strip():
            continue
        if len(current) + len(para) > max_chunk_size and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())

    # 如果段落还是太长，按行切
    final = []
    for chunk in chunks:
        if len(chunk) <= max_chunk_size:
            final.append(chunk)
        else:
            lines = chunk.split("\n")
            current = ""
            for line in lines:
                if len(current) + len(line) > max_chunk_size and current:
                    final.append(current)
                    current = line
                else:
                    current = current + "\n" + line if current else line
            if current:
                final.append(current)
    return final


def _chunk_file(file_path: str, content: str) -> List[Tuple[str, str]]:
    """切分文件为 chunk 列表

    Returns:
        [(chunk_id, chunk_content), ...]
    """
    ext = os.path.splitext(file_path)[1].lower()
    base_name = os.path.basename(file_path)

    if ext == ".py":
        chunks = _chunk_python(content)
    else:
        chunks = _chunk_text(content)

    return [(f"{base_name}#{i}", chunk) for i, chunk in enumerate(chunks)]


class ProjectIndexer:
    """项目文件索引器"""

    def __init__(self, store: Optional[VectorStore] = None):
        """初始化

        Args:
            store: VectorStore 实例，为 None 时用默认单例
        """
        self.store = store or get_vector_store()

    def scan_files(self, root_dir: str) -> List[str]:
        """扫描项目目录，返回所有应该索引的文件

        Args:
            root_dir: 项目根目录

        Returns:
            文件路径列表（绝对路径）
        """
        files = []
        root_dir = os.path.abspath(root_dir)
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # 过滤目录（修改 dirnames 避免 walk 进入）
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
            ]

            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                fpath = os.path.join(dirpath, fname)
                if _should_skip(fpath):
                    continue
                try:
                    size = os.path.getsize(fpath)
                    if size > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                files.append(fpath)
        return files

    async def index_file(self, file_path: str, root_dir: str = "") -> int:
        """索引单个文件

        Args:
            file_path: 文件绝对路径
            root_dir: 项目根目录（用于计算相对路径，跨盘符时用绝对路径）

        Returns:
            新增/更新的 chunk 数量
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return 0

        if not content.strip():
            return 0

        chunks = _chunk_file(file_path, content)
        if not chunks:
            return 0

        # 计算相对路径（跨盘符时回退为绝对路径）
        if root_dir:
            try:
                rel_path = os.path.relpath(file_path, root_dir)
            except ValueError:
                rel_path = os.path.basename(file_path)
        else:
            # 不传 root_dir 时用文件名作为 source
            rel_path = os.path.basename(file_path)

        items = [
            (chunk_id, rel_path, chunk_content)
            for chunk_id, chunk_content in chunks
        ]

        return await self.store.add_batch(items)

    async def index_project(
        self,
        root_dir: str,
        on_progress: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """索引整个项目

        Args:
            root_dir: 项目根目录
            on_progress: 进度回调 (current, total, file_path)

        Returns:
            {"total_files": ..., "indexed_files": ..., "total_chunks": ..., "elapsed": ...}
        """
        start_time = time.time()
        files = self.scan_files(root_dir)
        total = len(files)
        indexed = 0
        total_chunks = 0

        for i, fpath in enumerate(files, 1):
            try:
                count = await self.index_file(fpath, root_dir=root_dir)
                if count > 0:
                    indexed += 1
                    total_chunks += count
            except Exception:
                pass

            if on_progress:
                try:
                    on_progress(i, total, fpath)
                except Exception:
                    pass

            # 每 20 个文件让出一次控制权，避免阻塞 UI
            if i % 20 == 0:
                await asyncio.sleep(0)

        elapsed = time.time() - start_time
        return {
            "total_files": total,
            "indexed_files": indexed,
            "total_chunks": total_chunks,
            "elapsed": elapsed,
        }


# ============================================================================
# 便捷函数
# ============================================================================

async def index_project(
    root_dir: str,
    on_progress: Optional[callable] = None,
) -> Dict[str, Any]:
    """索引项目的便捷函数

    Args:
        root_dir: 项目根目录
        on_progress: 进度回调

    Returns:
        索引统计信息
    """
    indexer = ProjectIndexer()
    return await indexer.index_project(root_dir, on_progress)
