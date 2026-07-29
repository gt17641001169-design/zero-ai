"""项目代码知识图谱（阶段 Q.1 + Q.2）

基于 AST 解析构建项目代码的结构化知识图谱，支持自然语言查询。

阶段 Q.1：AST 解析与图谱构建
- 解析 Python 文件 AST，提取模块/类/函数/变量节点
- 提取调用关系、继承关系、导入关系、定义关系
- 构建有向图（节点=代码实体，边=关系）

阶段 Q.2：自然语言查询代码结构
- 提供自然语言查询接口（基于关键词匹配 + 图谱遍历）
- 支持常见查询：调用者/被调用者/子类/父类/定义位置/调用链

设计原则：
1. 零外部依赖：仅用标准库 ast + collections
2. 增量解析：单文件解析 + 项目级聚合
3. 容错：解析失败不阻断，跳过错误文件
4. 可序列化：图谱可转为 dict/JSON 便于持久化

使用方式：
    graph = CodeKnowledgeGraph()
    graph.index_file("zeroai/core/agent.py")
    graph.index_directory("zeroai")

    # 查询
    callers = graph.find_callers("run_command")
    subclasses = graph.find_subclasses("AgentLoop")
    chain = graph.get_call_chain("run_command")
    answer = graph.query("谁调用了 run_command 函数？")
"""
from __future__ import annotations

import ast
import os
import re
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple, Union


# ============================================================================
# 数据结构定义（阶段 Q.1.1）
# ============================================================================

@dataclass
class CodeNode:
    """代码节点：代表一个代码实体

    类型：
    - module: 模块（文件级）
    - class: 类
    - function: 函数/方法
    - method: 类方法（带类前缀）
    - variable: 模块级变量/常量
    - import: 导入项
    """
    id: str  # 唯一标识，如 "zeroai.core.agent:AgentLoop.run"
    name: str  # 简短名称，如 "run"
    qualified_name: str  # 完整限定名，如 "AgentLoop.run"
    node_type: str  # module / class / function / method / variable / import
    file_path: str  # 源文件路径
    line_start: int = 0
    line_end: int = 0
    docstring: str = ""
    signature: str = ""  # 函数签名/类定义行
    parent_id: Optional[str] = None  # 父节点（如方法所属的类）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CodeEdge:
    """代码边：代码实体间的关系

    类型：
    - calls: A 调用 B
    - inherits: A 继承自 B
    - imports: A 导入 B
    - contains: A 包含 B（模块包含类，类包含方法）
    - defines: A 定义 B（模块定义变量）
    - references: A 引用 B（变量引用）
    """
    source: str  # 源节点 id
    target: str  # 目标节点 id
    edge_type: str  # calls / inherits / imports / contains / defines / references
    file_path: str = ""
    line: int = 0
    weight: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# AST 访问器：解析单个 Python 文件（阶段 Q.1.2）
# ============================================================================

class _FileASTVisitor(ast.NodeVisitor):
    """AST 访问器：提取单个文件中的代码结构

    提取内容：
    1. 模块节点（文件本身）
    2. 顶层导入
    3. 顶层函数和类
    4. 类方法
    5. 函数调用（calls 边）
    6. 继承关系（inherits 边）
    7. 包含关系（contains 边）
    """

    def __init__(self, file_path: str, module_id: str):
        self.file_path = file_path
        self.module_id = module_id
        self.nodes: List[CodeNode] = []
        self.edges: List[CodeEdge] = []
        self._scope_stack: List[str] = []  # 当前作用域栈
        self._class_stack: List[str] = []  # 当前类栈

    def _make_id(self, name: str) -> str:
        """构造节点 id"""
        parts = [self.module_id]
        if self._class_stack:
            parts.append(".".join(self._class_stack))
        parts.append(name)
        return ":".join(parts)

    def _make_qualified_name(self, name: str) -> str:
        """构造限定名"""
        if self._class_stack:
            return ".".join(self._class_stack + [name])
        return name

    def _get_docstring(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module]) -> str:
        """提取 docstring"""
        try:
            return ast.get_docstring(node) or ""
        except Exception:
            return ""

    def _get_signature(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> str:
        """提取函数签名"""
        try:
            args = []
            for arg in node.args.args:
                arg_str = arg.arg
                if arg.annotation:
                    arg_str += f": {ast.unparse(arg.annotation)}"
                args.append(arg_str)
            # 默认值
            defaults = [ast.unparse(d) for d in node.args.defaults]
            if defaults:
                num_defaults = len(defaults)
                num_args = len(args)
                for i in range(num_defaults):
                    args[num_args - num_defaults + i] += f"={defaults[i]}"
            # *args / **kwargs
            if node.args.vararg:
                args.append(f"*{node.args.vararg.arg}")
            if node.args.kwarg:
                args.append(f"**{node.args.kwarg.arg}")
            sig = f"def {node.name}({', '.join(args)})"
            if node.returns:
                sig += f" -> {ast.unparse(node.returns)}"
            return sig
        except Exception:
            return f"def {node.name}(...)"

    def visit_Module(self, node: ast.Module) -> None:
        """访问模块（文件）"""
        # 创建模块节点
        module_node = CodeNode(
            id=self.module_id,
            name=os.path.basename(self.file_path),
            qualified_name=self.module_id,
            node_type="module",
            file_path=self.file_path,
            line_start=1,
            line_end=len(node.body) if hasattr(node, "body") else 0,
            docstring=self._get_docstring(node),
        )
        self.nodes.append(module_node)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """访问 import 语句"""
        for alias in node.names:
            name = alias.name
            asname = alias.asname or name
            node_id = f"{self.module_id}:import:{asname}"
            import_node = CodeNode(
                id=node_id,
                name=asname,
                qualified_name=asname,
                node_type="import",
                file_path=self.file_path,
                line_start=getattr(node, "lineno", 0),
                line_end=getattr(node, "end_lineno", 0) or getattr(node, "lineno", 0),
                signature=f"import {name}" + (f" as {alias.asname}" if alias.asname else ""),
            )
            self.nodes.append(import_node)
            self.edges.append(CodeEdge(
                source=self.module_id,
                target=node_id,
                edge_type="imports",
                file_path=self.file_path,
                line=getattr(node, "lineno", 0),
            ))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """访问 from ... import 语句"""
        module = node.module or ""
        for alias in node.names:
            name = alias.name
            asname = alias.asname or name
            node_id = f"{self.module_id}:import:{asname}"
            import_node = CodeNode(
                id=node_id,
                name=asname,
                qualified_name=asname,
                node_type="import",
                file_path=self.file_path,
                line_start=getattr(node, "lineno", 0),
                line_end=getattr(node, "end_lineno", 0) or getattr(node, "lineno", 0),
                signature=f"from {module} import {name}" + (f" as {alias.asname}" if alias.asname else ""),
            )
            self.nodes.append(import_node)
            self.edges.append(CodeEdge(
                source=self.module_id,
                target=node_id,
                edge_type="imports",
                file_path=self.file_path,
                line=getattr(node, "lineno", 0),
            ))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """访问函数定义"""
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """访问异步函数定义"""
        self._visit_function(node, is_async=True)

    def _visit_function(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef], is_async: bool = False) -> None:
        """处理函数/方法定义"""
        func_id = self._make_id(node.name)
        qualified = self._make_qualified_name(node.name)
        node_type = "method" if self._class_stack else "function"
        parent_id = self._class_stack[-1] if self._class_stack else self.module_id

        func_node = CodeNode(
            id=func_id,
            name=node.name,
            qualified_name=qualified,
            node_type=node_type,
            file_path=self.file_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            docstring=self._get_docstring(node),
            signature=self._get_signature(node),
            parent_id=parent_id,
        )
        self.nodes.append(func_node)
        # contains 边：父节点包含此函数
        parent_full_id = self._make_id(self._class_stack[-1]) if self._class_stack else self.module_id
        self.edges.append(CodeEdge(
            source=parent_full_id,
            target=func_id,
            edge_type="contains",
            file_path=self.file_path,
            line=node.lineno,
        ))

        # 进入函数作用域
        self._scope_stack.append(node.name)
        # 访问函数体，提取调用关系
        for stmt in node.body:
            self._collect_calls(stmt, func_id, node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """访问类定义"""
        class_id = self._make_id(node.name)
        qualified = self._make_qualified_name(node.name)

        # 提取基类
        base_names = []
        for base in node.bases:
            try:
                base_name = ast.unparse(base)
                base_names.append(base_name)
            except Exception:
                pass

        class_node = CodeNode(
            id=class_id,
            name=node.name,
            qualified_name=qualified,
            node_type="class",
            file_path=self.file_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            docstring=self._get_docstring(node),
            signature=f"class {node.name}({', '.join(base_names)})" if base_names else f"class {node.name}",
            parent_id=self.module_id,
        )
        self.nodes.append(class_node)
        # contains 边：模块包含类
        self.edges.append(CodeEdge(
            source=self.module_id,
            target=class_id,
            edge_type="contains",
            file_path=self.file_path,
            line=node.lineno,
        ))

        # 继承边（基类名作为 target，跨文件解析时再补全）
        for base_name in base_names:
            # 简化：用基类名作为临时 target，后续解析时再补全为完整 id
            base_target = f"__external__:{base_name}"
            self.edges.append(CodeEdge(
                source=class_id,
                target=base_target,
                edge_type="inherits",
                file_path=self.file_path,
                line=node.lineno,
            ))

        # 进入类作用域
        self._class_stack.append(node.name)
        # 访问类体（方法、属性等）
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 方法会被 visit_FunctionDef 处理
                pass
        self.generic_visit(node)
        self._class_stack.pop()

    def _collect_calls(self, node: ast.AST, caller_id: str, caller_name: str) -> None:
        """收集函数调用关系"""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                callee_name = self._get_call_name(child.func)
                if not callee_name:
                    continue
                # 跳过 self.xxx / cls.xxx 这种内部方法调用（可选）
                # 这里保留，便于分析
                callee_target = f"__external__:{callee_name}"
                self.edges.append(CodeEdge(
                    source=caller_id,
                    target=callee_target,
                    edge_type="calls",
                    file_path=self.file_path,
                    line=getattr(child, "lineno", 0),
                ))

    def _get_call_name(self, node: ast.AST) -> str:
        """从 Call.func 提取被调用函数名"""
        try:
            if isinstance(node, ast.Name):
                return node.id
            elif isinstance(node, ast.Attribute):
                # foo.bar.baz -> "foo.bar.baz"
                parts = []
                cur = node
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                    return ".".join(reversed(parts))
                return node.attr
            elif isinstance(node, ast.Subscript):
                return self._get_call_name(node.value)
        except Exception:
            pass
        return ""


# ============================================================================
# 代码知识图谱（阶段 Q.1.3）
# ============================================================================

class CodeKnowledgeGraph:
    """项目代码知识图谱

    构建项目代码的结构化图谱，支持查询。

    使用方式：
        graph = CodeKnowledgeGraph()
        graph.index_directory("zeroai")
        callers = graph.find_callers("run_command")
        subclasses = graph.find_subclasses("AgentLoop")
    """

    # 支持解析的文件扩展名
    SUPPORTED_EXTENSIONS = {".py"}

    # 跳过的目录
    SKIP_DIRS = {
        "node_modules", "__pycache__", ".git", ".svn", ".hg",
        "dist", "build", "target", "out", ".next", ".nuxt",
        ".venv", "venv", "env", ".env",
        ".idea", ".vscode", ".trae-cn",
        "site-packages", "egg-info",
        ".pytest_cache", ".mypy_cache", ".ruff_cache",
    }

    def __init__(self):
        self.nodes: Dict[str, CodeNode] = {}  # id -> CodeNode
        self.edges: List[CodeEdge] = []
        # 索引：加速查询
        self._nodes_by_name: Dict[str, List[str]] = defaultdict(list)  # name -> [node_id]
        self._nodes_by_type: Dict[str, List[str]] = defaultdict(list)  # type -> [node_id]
        self._edges_by_source: Dict[str, List[CodeEdge]] = defaultdict(list)
        self._edges_by_target: Dict[str, List[CodeEdge]] = defaultdict(list)
        self._edges_by_type: Dict[str, List[CodeEdge]] = defaultdict(list)
        # 模块路径映射：module_id -> file_path
        self._module_paths: Dict[str, str] = {}
        # 外部符号解析映射：__external__:Name -> resolved_node_id
        self._external_resolved: Dict[str, str] = {}

    def _module_id_from_path(self, file_path: str, root_dir: str = "") -> str:
        """从文件路径生成 module_id

        例如：zeroai/core/agent.py + root=zeroai -> "zeroai.core.agent"
        """
        try:
            rel = os.path.relpath(file_path, root_dir) if root_dir else file_path
        except ValueError:
            rel = file_path
        # 替换路径分隔符
        rel = rel.replace("\\", "/")
        # 去掉 .py 扩展名
        if rel.endswith(".py"):
            rel = rel[:-3]
        # 替换 / 为 .
        module_id = rel.replace("/", ".")
        # 去掉开头的 .
        module_id = module_id.lstrip(".")
        return module_id or "__main__"

    def index_file(self, file_path: str, root_dir: str = "") -> int:
        """索引单个 Python 文件

        Args:
            file_path: 文件绝对路径
            root_dir: 项目根目录（用于生成 module_id）

        Returns:
            新增节点数（失败返回 0）
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
        except OSError:
            return 0

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return 0
        except Exception:
            return 0

        module_id = self._module_id_from_path(file_path, root_dir)
        visitor = _FileASTVisitor(file_path, module_id)
        visitor.visit(tree)

        # 添加节点和边
        for node in visitor.nodes:
            self.nodes[node.id] = node
            self._nodes_by_name[node.name].append(node.id)
            self._nodes_by_type[node.node_type].append(node.id)
            if node.node_type == "module":
                self._module_paths[module_id] = file_path

        for edge in visitor.edges:
            self.edges.append(edge)
            self._edges_by_source[edge.source].append(edge)
            self._edges_by_target[edge.target].append(edge)
            self._edges_by_type[edge.edge_type].append(edge)

        return len(visitor.nodes)

    def index_directory(
        self,
        root_dir: str,
        on_progress: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """索引整个项目目录

        Args:
            root_dir: 项目根目录
            on_progress: 进度回调 (current, total, file_path)

        Returns:
            索引统计信息
        """
        start_time = time.time()
        root_dir = os.path.abspath(root_dir)
        files = self._scan_python_files(root_dir)
        total = len(files)
        indexed = 0
        total_nodes = 0

        for i, fpath in enumerate(files, 1):
            try:
                count = self.index_file(fpath, root_dir=root_dir)
                if count > 0:
                    indexed += 1
                    total_nodes += count
            except Exception:
                pass
            if on_progress:
                try:
                    on_progress(i, total, fpath)
                except Exception:
                    pass

        # 第二轮：解析外部符号引用（跨文件调用/继承）
        self._resolve_external_references()

        elapsed = time.time() - start_time
        return {
            "total_files": total,
            "indexed_files": indexed,
            "total_nodes": total_nodes,
            "total_edges": len(self.edges),
            "elapsed": round(elapsed, 3),
        }

    def _scan_python_files(self, root_dir: str) -> List[str]:
        """扫描项目目录中的 Python 文件"""
        files = []
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [
                d for d in dirnames
                if d not in self.SKIP_DIRS and not d.startswith(".")
            ]
            for fname in filenames:
                if fname.endswith(".py"):
                    fpath = os.path.join(dirpath, fname)
                    files.append(fpath)
        return files

    def _resolve_external_references(self) -> None:
        """解析 __external__:Name 引用为实际节点 id

        策略：
        1. 对每个 __external__:Name，在所有节点中查找匹配
        2. 优先匹配：完全限定名 > 简单名 > 末尾名
        3. 解析后更新边的 target
        """
        # 收集所有外部符号
        external_names: Set[str] = set()
        for edge in self.edges:
            if edge.target.startswith("__external__:"):
                external_names.add(edge.target[len("__external__:"):])

        # 为每个外部符号查找匹配节点
        name_to_ids: Dict[str, List[str]] = defaultdict(list)
        for name, ids in self._nodes_by_name.items():
            name_to_ids[name].extend(ids)
        # 也按限定名末尾段建立索引
        for node_id, node in self.nodes.items():
            if node.node_type in ("function", "method", "class"):
                last_seg = node.qualified_name.split(".")[-1]
                name_to_ids[last_seg].append(node_id)

        # 解析并更新边
        for edge in self.edges:
            if not edge.target.startswith("__external__:"):
                continue
            ext_name = edge.target[len("__external__:"):]
            # 去掉实例前缀，如 "self.run_command" -> "run_command"
            if "." in ext_name:
                ext_name = ext_name.split(".")[-1]
            candidates = name_to_ids.get(ext_name, [])
            if candidates:
                # 取第一个匹配（最简单策略）
                resolved_id = candidates[0]
                self._external_resolved[edge.target] = resolved_id
                edge.target = resolved_id

    # ========================================================================
    # 查询接口（阶段 Q.2）
    # ========================================================================

    def find_node(self, name: str) -> Optional[CodeNode]:
        """按名称查找节点（精确匹配简单名）"""
        ids = self._nodes_by_name.get(name, [])
        if ids:
            return self.nodes.get(ids[0])
        return None

    def find_nodes(self, name: str) -> List[CodeNode]:
        """按名称查找所有匹配节点"""
        ids = self._nodes_by_name.get(name, [])
        return [self.nodes[i] for i in ids if i in self.nodes]

    def find_callers(self, func_name: str) -> List[CodeNode]:
        """查找调用指定函数的所有节点

        Args:
            func_name: 函数名（简单名或限定名）

        Returns:
            调用者节点列表
        """
        # 找到所有名为 func_name 的被调用者节点 id
        target_ids: Set[str] = set()
        for node_id, node in self.nodes.items():
            if node.name == func_name or node.qualified_name.endswith(func_name):
                target_ids.add(node_id)
        # 也匹配未解析的外部引用
        ext_target = f"__external__:{func_name}"
        target_ids.add(ext_target)

        callers: List[CodeNode] = []
        seen: Set[str] = set()
        for edge in self.edges:
            if edge.edge_type == "calls" and edge.target in target_ids:
                if edge.source in self.nodes and edge.source not in seen:
                    callers.append(self.nodes[edge.source])
                    seen.add(edge.source)
        return callers

    def find_callees(self, func_name: str) -> List[CodeNode]:
        """查找指定函数调用的所有函数

        Args:
            func_name: 函数名

        Returns:
            被调用者节点列表
        """
        source_ids: Set[str] = set()
        for node_id, node in self.nodes.items():
            if node.name == func_name or node.qualified_name.endswith(func_name):
                source_ids.add(node_id)

        callees: List[CodeNode] = []
        seen: Set[str] = set()
        for edge in self.edges:
            if edge.edge_type == "calls" and edge.source in source_ids:
                if edge.target in self.nodes and edge.target not in seen:
                    callees.append(self.nodes[edge.target])
                    seen.add(edge.target)
        return callees

    def find_subclasses(self, class_name: str) -> List[CodeNode]:
        """查找指定类的所有子类

        Args:
            class_name: 类名

        Returns:
            子类节点列表
        """
        target_ids: Set[str] = set()
        for node_id, node in self.nodes.items():
            if node.name == class_name or node.qualified_name.endswith(class_name):
                target_ids.add(node_id)
        target_ids.add(f"__external__:{class_name}")

        subclasses: List[CodeNode] = []
        seen: Set[str] = set()
        for edge in self.edges:
            if edge.edge_type == "inherits" and edge.target in target_ids:
                if edge.source in self.nodes and edge.source not in seen:
                    subclasses.append(self.nodes[edge.source])
                    seen.add(edge.source)
        return subclasses

    def find_superclasses(self, class_name: str) -> List[CodeNode]:
        """查找指定类的所有父类

        Args:
            class_name: 类名

        Returns:
            父类节点列表
        """
        source_ids: Set[str] = set()
        for node_id, node in self.nodes.items():
            if node.name == class_name or node.qualified_name.endswith(class_name):
                source_ids.add(node_id)

        supers: List[CodeNode] = []
        seen: Set[str] = set()
        for edge in self.edges:
            if edge.edge_type == "inherits" and edge.source in source_ids:
                if edge.target in self.nodes and edge.target not in seen:
                    supers.append(self.nodes[edge.target])
                    seen.add(edge.target)
        return supers

    def find_definitions(self, name: str) -> List[CodeNode]:
        """查找名称的所有定义位置

        Args:
            name: 函数/类/变量名

        Returns:
            定义节点列表
        """
        return self.find_nodes(name)

    def get_module_functions(self, module_name: str) -> List[CodeNode]:
        """获取模块中定义的所有函数"""
        result = []
        for node in self.nodes.values():
            if node.node_type in ("function",) and node.parent_id == module_name:
                result.append(node)
        return result

    def get_module_classes(self, module_name: str) -> List[CodeNode]:
        """获取模块中定义的所有类"""
        result = []
        for node in self.nodes.values():
            if node.node_type == "class" and node.parent_id == module_name:
                result.append(node)
        return result

    def get_class_methods(self, class_name: str) -> List[CodeNode]:
        """获取类的所有方法"""
        class_node = self.find_node(class_name)
        if not class_node:
            return []
        result = []
        for node in self.nodes.values():
            if node.node_type == "method" and node.parent_id == class_node.id:
                result.append(node)
        return result

    def get_call_chain(
        self,
        func_name: str,
        max_depth: int = 5,
        direction: str = "up",
    ) -> List[List[CodeNode]]:
        """获取调用链

        Args:
            func_name: 起始函数名
            max_depth: 最大深度
            direction: "up"（向上找调用者）或 "down"（向下找被调用者）

        Returns:
            调用链列表，每条链是从起始节点到末端的节点序列
        """
        start_nodes = self.find_nodes(func_name)
        if not start_nodes:
            return []

        chains: List[List[CodeNode]] = []
        for start in start_nodes:
            self._dfs_chain(start, [], chains, max_depth, direction, set())
        return chains

    def _dfs_chain(
        self,
        node: CodeNode,
        path: List[CodeNode],
        chains: List[List[CodeNode]],
        max_depth: int,
        direction: str,
        visited: Set[str],
    ) -> None:
        """深度优先搜索调用链"""
        if node.id in visited:
            return
        new_path = path + [node]
        new_visited = visited | {node.id}

        if len(new_path) >= max_depth:
            chains.append(new_path)
            return

        # 获取下一跳节点
        next_nodes: List[CodeNode] = []
        if direction == "up":
            # 向上找调用者
            for edge in self._edges_by_type.get("calls", []):
                if edge.target == node.id:
                    if edge.source in self.nodes:
                        next_nodes.append(self.nodes[edge.source])
        else:
            # 向下找被调用者
            for edge in self._edges_by_type.get("calls", []):
                if edge.source == node.id:
                    if edge.target in self.nodes:
                        next_nodes.append(self.nodes[edge.target])

        if not next_nodes:
            chains.append(new_path)
            return

        for next_node in next_nodes:
            self._dfs_chain(next_node, new_path, chains, max_depth, direction, new_visited)

    # ========================================================================
    # 自然语言查询（阶段 Q.2）
    # ========================================================================

    def query(self, question: str) -> str:
        """自然语言查询代码结构

        Args:
            question: 自然语言问题（中文）

        Returns:
            答案字符串

        支持的查询模式：
        - 谁调用了 X / X 的调用者 / 谁用了 X
        - X 调用了谁 / X 调用什么 / X 的被调用者
        - X 的子类 / 继承自 X 的类 / X 的派生类
        - X 的父类 / X 继承自谁 / X 的基类
        - X 定义在哪里 / X 在哪定义 / X 的定义位置
        - X 模块有哪些函数 / X 模块的函数
        - X 类有哪些方法 / X 类的方法
        - X 的调用链 / X 的调用路径
        """
        q = question.strip()
        if not q:
            return "请提供查询问题"

        # 提取问题中的标识符（去掉常见中文问句词）
        # 简单策略：找到引号内容，或最长英文标识符
        identifier = self._extract_identifier(q)
        if not identifier:
            return "未识别出要查询的标识符，请在问题中包含函数名/类名"

        # 模式匹配
        patterns = [
            # 调用者查询
            (r"谁调用了|谁用了|的调用者|调用\s*{id}\s*的|谁.*调用.*{id}", "callers"),
            # 被调用者查询
            (r"调用了谁|调用什么|的被调用者|{id}.*调用.*谁|{id}.*调用.*什么", "callees"),
            # 子类查询
            (r"子类|派生类|继承自.*的类", "subclasses"),
            # 父类查询
            (r"父类|基类|继承自谁|继承自什么", "superclasses"),
            # 定义位置查询
            (r"定义在哪里|在哪定义|定义位置|哪里定义", "definition"),
            # 模块函数查询
            (r"模块.*函数|有哪些函数|的函数", "module_functions"),
            # 类方法查询
            (r"类.*方法|有哪些方法|的方法", "class_methods"),
            # 调用链查询
            (r"调用链|调用路径|调用关系", "call_chain"),
        ]

        for pattern, query_type in patterns:
            try:
                pattern_with_id = pattern.format(id=re.escape(identifier))
                if re.search(pattern_with_id, q):
                    return self._format_query_result(query_type, identifier)
            except Exception:
                continue

        # 兜底：默认查询定义位置
        return self._format_query_result("definition", identifier)

    def _extract_identifier(self, question: str) -> str:
        """从自然语言问题中提取标识符

        策略：
        1. 优先匹配引号中的内容
        2. 匹配点号分隔的标识符（如 "AgentLoop.run"）
        3. 匹配单个英文标识符
        """
        # 引号中的内容
        m = re.search(r'["\'`]([a-zA-Z_][a-zA-Z0-9_.]*)["\'`]', question)
        if m:
            return m.group(1)

        # 点号分隔的标识符
        m = re.search(r'\b([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\b', question)
        if m:
            return m.group(1)

        # 单个英文标识符（最长的那个）
        matches = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]{2,})\b', question)
        if matches:
            # 过滤掉常见问句词
            stop_words = {
                "who", "what", "where", "when", "why", "how",
                "the", "and", "for", "with", "from", "into",
                "find", "list", "show", "get", "query", "search",
                "all", "any", "some", "which",
                "的", "是", "在", "有", "和", "与", "及",
                "调用", "继承", "定义", "查询", "查找", "显示", "列出", "获取",
                "谁", "什么", "哪里", "哪个", "哪些", "多少", "如何",
                "模块", "函数", "类", "方法", "变量", "属性",
            }
            candidates = [m for m in matches if m.lower() not in stop_words]
            if candidates:
                # 返回最长的候选
                return max(candidates, key=len)

        return ""

    def _format_query_result(self, query_type: str, identifier: str) -> str:
        """格式化查询结果"""
        if query_type == "callers":
            results = self.find_callers(identifier)
            if not results:
                return f"未找到调用 '{identifier}' 的位置"
            lines = [f"调用 '{identifier}' 的位置（共 {len(results)} 处）："]
            for node in results[:20]:
                lines.append(f"  - {node.qualified_name} ({node.file_path}:{node.line_start})")
            if len(results) > 20:
                lines.append(f"  ... 还有 {len(results) - 20} 处")
            return "\n".join(lines)

        elif query_type == "callees":
            results = self.find_callees(identifier)
            if not results:
                return f"未找到 '{identifier}' 调用的函数"
            lines = [f"'{identifier}' 调用的函数（共 {len(results)} 个）："]
            for node in results[:20]:
                lines.append(f"  - {node.qualified_name} ({node.file_path}:{node.line_start})")
            if len(results) > 20:
                lines.append(f"  ... 还有 {len(results) - 20} 个")
            return "\n".join(lines)

        elif query_type == "subclasses":
            results = self.find_subclasses(identifier)
            if not results:
                return f"未找到继承自 '{identifier}' 的子类"
            lines = [f"继承自 '{identifier}' 的子类（共 {len(results)} 个）："]
            for node in results[:20]:
                lines.append(f"  - {node.qualified_name} ({node.file_path}:{node.line_start})")
            return "\n".join(lines)

        elif query_type == "superclasses":
            results = self.find_superclasses(identifier)
            if not results:
                return f"未找到 '{identifier}' 的父类"
            lines = [f"'{identifier}' 的父类（共 {len(results)} 个）："]
            for node in results[:20]:
                lines.append(f"  - {node.qualified_name} ({node.file_path}:{node.line_start})")
            return "\n".join(lines)

        elif query_type == "definition":
            results = self.find_definitions(identifier)
            if not results:
                return f"未找到 '{identifier}' 的定义"
            lines = [f"'{identifier}' 的定义位置（共 {len(results)} 处）："]
            for node in results[:20]:
                type_label = {"module": "模块", "class": "类", "function": "函数", "method": "方法", "variable": "变量", "import": "导入"}.get(node.node_type, node.node_type)
                lines.append(f"  - [{type_label}] {node.qualified_name}")
                lines.append(f"    文件: {node.file_path}:{node.line_start}-{node.line_end}")
                if node.signature:
                    lines.append(f"    签名: {node.signature}")
                if node.docstring:
                    lines.append(f"    文档: {node.docstring[:100]}{'...' if len(node.docstring) > 100 else ''}")
            return "\n".join(lines)

        elif query_type == "module_functions":
            results = self.get_module_functions(identifier)
            if not results:
                return f"未找到模块 '{identifier}' 的函数"
            lines = [f"模块 '{identifier}' 的函数（共 {len(results)} 个）："]
            for node in results[:30]:
                lines.append(f"  - {node.name} ({node.line_start})")
            return "\n".join(lines)

        elif query_type == "class_methods":
            results = self.get_class_methods(identifier)
            if not results:
                return f"未找到类 '{identifier}' 的方法"
            lines = [f"类 '{identifier}' 的方法（共 {len(results)} 个）："]
            for node in results[:30]:
                lines.append(f"  - {node.name} ({node.line_start})")
            return "\n".join(lines)

        elif query_type == "call_chain":
            chains = self.get_call_chain(identifier, max_depth=5, direction="up")
            if not chains:
                return f"未找到 '{identifier}' 的调用链"
            lines = [f"'{identifier}' 的调用链（向上，共 {len(chains)} 条）："]
            for i, chain in enumerate(chains[:5], 1):
                chain_str = " → ".join(n.qualified_name for n in chain)
                lines.append(f"  {i}. {chain_str}")
            return "\n".join(lines)

        return f"未识别的查询类型: {query_type}"

    # ========================================================================
    # 统计与序列化
    # ========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取图谱统计信息"""
        type_counts: Dict[str, int] = defaultdict(int)
        for node in self.nodes.values():
            type_counts[node.node_type] += 1

        edge_type_counts: Dict[str, int] = defaultdict(int)
        for edge in self.edges:
            edge_type_counts[edge.edge_type] += 1

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "node_types": dict(type_counts),
            "edge_types": dict(edge_type_counts),
            "modules_indexed": len(self._module_paths),
            "external_resolved": len(self._external_resolved),
        }

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "stats": self.get_stats(),
        }

    def to_json(self, indent: int = 2) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def clear(self) -> None:
        """清空图谱"""
        self.nodes.clear()
        self.edges.clear()
        self._nodes_by_name.clear()
        self._nodes_by_type.clear()
        self._edges_by_source.clear()
        self._edges_by_target.clear()
        self._edges_by_type.clear()
        self._module_paths.clear()
        self._external_resolved.clear()


# ============================================================================
# 全局单例
# ============================================================================

_default_graph: Optional[CodeKnowledgeGraph] = None


def get_code_knowledge_graph() -> CodeKnowledgeGraph:
    """获取全局代码知识图谱单例"""
    global _default_graph
    if _default_graph is None:
        _default_graph = CodeKnowledgeGraph()
    return _default_graph


def reset_code_knowledge_graph() -> None:
    """重置全局代码知识图谱单例"""
    global _default_graph
    _default_graph = None


__all__ = [
    "CodeNode",
    "CodeEdge",
    "CodeKnowledgeGraph",
    "get_code_knowledge_graph",
    "reset_code_knowledge_graph",
]
