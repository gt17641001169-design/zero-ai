"""File operation tools for ZeroAI"""
import os
import shutil
from pathlib import Path
from typing import Optional
from .base import Tool, ToolExecutionError, register_tool


@register_tool
class ReadFileTool(Tool):
    """Read file content"""
    
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
        """Read file content"""
        try:
            file_path = Path(path)
            if not file_path.exists():
                return f"错误：文件不存在 - {path}"
            
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            # Apply offset and limit
            selected_lines = lines[offset:offset + limit]
            content = ''.join(selected_lines)
            
            # Add line numbers
            numbered_lines = []
            for i, line in enumerate(selected_lines, start=offset + 1):
                numbered_lines.append(f"{i:4d}: {line.rstrip()}")
            
            return '\n'.join(numbered_lines)
            
        except Exception as e:
            raise ToolExecutionError(f"读取文件失败: {e}")


@register_tool
class WriteFileTool(Tool):
    """Write content to file"""
    
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
        """Write content to file"""
        try:
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return f"文件已写入: {path} ({len(content)} 字符)"
            
        except Exception as e:
            raise ToolExecutionError(f"写入文件失败: {e}")


@register_tool
class ListDirTool(Tool):
    """List directory contents"""
    
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
        """List directory contents"""
        try:
            dir_path = Path(path)
            if not dir_path.exists():
                return f"错误：目录不存在 - {path}"
            
            if not dir_path.is_dir():
                return f"错误：不是目录 - {path}"
            
            result = []
            self._list_directory(dir_path, result, recursive, max_depth, 0)
            
            return '\n'.join(result)
            
        except Exception as e:
            raise ToolExecutionError(f"列出目录失败: {e}")
    
    def _list_directory(self, path: Path, result: list, recursive: bool, max_depth: int, current_depth: int):
        """Helper method for recursive directory listing"""
        if current_depth > max_depth:
            return
        
        try:
            items = sorted(path.iterdir())
            for item in items:
                prefix = "  " * current_depth
                if item.is_dir():
                    result.append(f"{prefix}📁 {item.name}/")
                    if recursive:
                        self._list_directory(item, result, recursive, max_depth, current_depth + 1)
                else:
                    size = item.stat().st_size
                    result.append(f"{prefix}📄 {item.name} ({size} bytes)")
        except PermissionError:
            result.append(f"{prefix}⚠️ Permission denied: {path}")
        except Exception as e:
            result.append(f"{prefix}⚠️ Error: {e}")


@register_tool
class SearchFilesTool(Tool):
    """Search files by name or content"""
    
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
        """Search files"""
        try:
            dir_path = Path(path)
            if not dir_path.exists():
                return f"错误：目录不存在 - {path}"
            
            results = []
            pattern_lower = pattern.lower()
            
            for item in dir_path.rglob("*"):
                if item.is_file():
                    if search_content:
                        # Search in file content
                        try:
                            with open(item, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                            if pattern_lower in content.lower():
                                results.append(str(item))
                        except:
                            pass
                    else:
                        # Search in filename
                        if pattern_lower in item.name.lower():
                            results.append(str(item))
            
            if not results:
                return f"未找到匹配 '{pattern}' 的文件"
            
            return f"找到 {len(results)} 个匹配文件:\n" + '\n'.join(results[:20])
            
        except Exception as e:
            raise ToolExecutionError(f"搜索文件失败: {e}")
