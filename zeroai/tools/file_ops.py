"""File operation tools for ZeroAI（薄包装层）

本模块是早期实现的类版工具，现已统一委托到 file_manager.py 的函数实现。
保留此类版是为了：
1. 向后兼容：ToolRegistry 注册的类版工具仍可用
2. 类型提示：某些场景需要 Tool 抽象基类的 to_schema() 接口

去重策略（阶段 D.1）：
- 所有 execute() 方法委托到 file_manager.py 的纯函数
- 不再维护独立逻辑，避免双份代码漂移
- file_manager.py 是唯一权威实现

迁移来源：tui_agent.py 早期实现 → file_manager.py（函数版，已注册到 TOOL_MAP）
"""
import os
import shutil
from pathlib import Path
from typing import Optional
from .base import Tool, ToolExecutionError, register_tool
from . import file_manager


@register_tool
class ReadFileTool(Tool):
    """Read file content（委托到 file_manager.read_file）"""

    name = "read_file"
    description = "Read the content of a file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read"
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (0-indexed)",
                "default": 0
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
                "default": 1000
            }
        },
        "required": ["path"]
    }

    def execute(self, path: str, offset: int = 0, limit: int = 1000) -> str:
        """Read file content（委托到 file_manager.read_file）

        注意：file_manager.read_file 用 max_length 而非 offset/limit，
        为保持兼容，这里做参数转换。
        """
        try:
            # 委托到 file_manager 的实现
            content = file_manager.read_file(path, max_length=limit * 100)

            # 如果指定了 offset，按行切片
            if offset > 0:
                lines = content.split("\n")
                selected = lines[offset:offset + limit]
                content = "\n".join(selected)

            return content
        except Exception as e:
            raise ToolExecutionError(f"读取文件失败: {e}")


@register_tool
class WriteFileTool(Tool):
    """Write content to file（委托到 file_manager.write_file）"""

    name = "write_file"
    description = "Write content to a file (creates or overwrites)"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            }
        },
        "required": ["path", "content"]
    }

    def execute(self, path: str, content: str) -> str:
        """Write content to file（委托到 file_manager.write_file）"""
        try:
            return file_manager.write_file(path, content)
        except Exception as e:
            raise ToolExecutionError(f"写入文件失败: {e}")


@register_tool
class ListDirTool(Tool):
    """List directory contents（委托到 file_manager.list_dir）"""

    name = "list_dir"
    description = "List contents of a directory"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the directory to list"
            },
            "recursive": {
                "type": "boolean",
                "description": "List recursively",
                "default": False
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth for recursive listing",
                "default": 3
            }
        },
        "required": ["path"]
    }

    def execute(self, path: str, recursive: bool = False, max_depth: int = 3) -> str:
        """List directory contents（委托到 file_manager.list_dir）"""
        try:
            # file_manager.list_dir 的 max_depth 默认 15，这里按调用方参数传递
            return file_manager.list_dir(path, recursive=recursive, max_depth=max_depth)
        except Exception as e:
            raise ToolExecutionError(f"列出目录失败: {e}")


@register_tool
class SearchFilesTool(Tool):
    """Search files by name or content（委托到 file_manager.search_files）"""

    name = "search_files"
    description = "Search for files by name pattern or content"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to search in"
            },
            "pattern": {
                "type": "string",
                "description": "Search pattern (filename or content)"
            },
            "search_content": {
                "type": "boolean",
                "description": "Search in file content instead of filename",
                "default": False
            }
        },
        "required": ["path", "pattern"]
    }

    def execute(self, path: str, pattern: str, search_content: bool = False) -> str:
        """Search files（委托到 file_manager.search_files）

        注意：file_manager.search_files 签名是 (pattern, path)，
        且只支持内容搜索。文件名搜索在这里保留独立实现。
        """
        try:
            if search_content:
                # 内容搜索委托到 file_manager
                return file_manager.search_files(pattern, path=path)
            else:
                # 文件名搜索保留独立实现（file_manager 无此功能）
                dir_path = Path(path)
                if not dir_path.exists():
                    return f"错误：目录不存在 - {path}"

                results = []
                pattern_lower = pattern.lower()

                for item in dir_path.rglob("*"):
                    if item.is_file():
                        if pattern_lower in item.name.lower():
                            results.append(str(item))

                if not results:
                    return f"未找到匹配 '{pattern}' 的文件"

                return f"找到 {len(results)} 个匹配文件:\n" + '\n'.join(results[:20])
        except Exception as e:
            raise ToolExecutionError(f"搜索文件失败: {e}")
