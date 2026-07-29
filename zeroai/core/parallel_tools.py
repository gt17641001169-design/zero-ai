"""工具调用并行化（阶段 S）

支持单步多工具并行调用，通过工具依赖图分析自动串行化有依赖的调用。

阶段 S.1：并行工具调度器
- 同一步骤内多个独立工具并行执行（asyncio.gather）
- 单个工具超时不影响其他工具
- 失败隔离：单个工具异常不影响整体流程

阶段 S.2：工具依赖图
- 静态分析工具间数据依赖（基于参数引用关系）
- 动态构建依赖图：同一批次内的工具调用按依赖排序
- 拓扑排序：无依赖的工具并行，有依赖的串行

阶段 S.3：结果合并器
- 并行工具结果的智能合并
- 按工具类型选择合并策略（文本拼接/字典合并/列表合并）
- 冲突消解：同名工具结果按优先级保留

阶段 S.4：超时隔离
- 每个工具有独立的超时控制
- 超时工具返回错误标记，不影响其他工具
- 支持全局超时和单工具超时

使用方式：
    from zeroai.core.parallel_tools import ParallelToolScheduler
    scheduler = ParallelToolScheduler(tool_map=TOOL_MAP, max_concurrency=4)
    # 单步多工具并行
    results = await scheduler.execute_parallel([
        ("read_file", {"path": "a.txt"}),
        ("read_file", {"path": "b.txt"}),
        ("system_info", {}),
    ])
"""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ============================================================================
# 数据结构（阶段 S.1）
# ============================================================================

@dataclass
class ToolCallRequest:
    """工具调用请求"""
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    timeout: Optional[float] = None  # 单工具超时（秒），None 用默认
    priority: int = 0  # 优先级（数字越大越优先）


@dataclass
class ToolCallResult:
    """工具调用结果"""
    name: str
    args: Dict[str, Any]
    result: str
    success: bool
    duration: float
    error: str = ""
    timed_out: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "args": self.args,
            "result": self.result,
            "success": self.success,
            "duration": self.duration,
            "error": self.error,
            "timed_out": self.timed_out,
        }


# ============================================================================
# 工具依赖图（阶段 S.2）
# ============================================================================

class ToolDependencyGraph:
    """工具依赖图

    分析工具调用间的数据依赖关系，用于决定是否可以并行执行。

    依赖判定策略：
    1. 写工具（write_file/delete_file/move_file/create_dir）之间串行
    2. 写工具与读工具（read_file/list_dir）对同一目标串行
    3. 不同目标的读写可并行
    4. 只读工具之间可并行
    """

    # 写操作工具集合（可能修改文件系统状态）
    WRITE_TOOLS = {
        "write_file", "delete_file", "move_file", "copy_file",
        "create_dir", "edit_file", "pip_install",
    }

    # 读操作工具集合（只读，无副作用）
    READ_TOOLS = {
        "read_file", "list_dir", "search_files", "file_diff",
        "system_info", "process_list", "check_port", "git_status",
        "read_image", "active_window", "list_windows", "read_screen",
        "security_audit", "code_check", "code_graph_stats",
    }

    # 网络工具（可能相互影响）
    NETWORK_TOOLS = {
        "web_search", "web_fetch", "open_app",
    }

    def __init__(self):
        self._dependencies: Dict[str, Set[str]] = {}  # tool_id -> depends_on_ids

    def analyze_batch(
        self,
        requests: List[ToolCallRequest],
    ) -> List[List[int]]:
        """分析一批工具调用的依赖关系，返回执行批次

        Returns:
            批次列表，每个批次是一组可并行执行的工具索引
            例如 [[0, 1, 2], [3, 4]] 表示前三个并行，完成后后两个并行
        """
        if not requests:
            return []

        # 单工具直接执行
        if len(requests) == 1:
            return [[0]]

        # 简化策略：按工具类型分组
        # 写工具按顺序串行，读工具可并行
        write_indices: List[int] = []
        read_indices: List[int] = []
        other_indices: List[int] = []

        for i, req in enumerate(requests):
            if req.name in self.WRITE_TOOLS:
                write_indices.append(i)
            elif req.name in self.READ_TOOLS:
                read_indices.append(i)
            else:
                other_indices.append(i)

        batches: List[List[int]] = []

        # 第一批：所有读工具 + 其他工具并行
        first_batch = read_indices + other_indices
        if first_batch:
            batches.append(first_batch)

        # 后续批次：写工具逐个串行（保守策略）
        for idx in write_indices:
            batches.append([idx])

        return batches

    def has_dependency(
        self,
        req_a: ToolCallRequest,
        req_b: ToolCallRequest,
    ) -> bool:
        """判断两个工具调用是否有依赖关系

        Returns:
            True 表示有依赖（必须串行），False 表示可并行
        """
        # 都是写工具：串行
        if req_a.name in self.WRITE_TOOLS and req_b.name in self.WRITE_TOOLS:
            return True

        # 一个写一个读：检查目标是否相同
        if req_a.name in self.WRITE_TOOLS and req_b.name in self.READ_TOOLS:
            return self._same_target(req_a, req_b)
        if req_b.name in self.WRITE_TOOLS and req_a.name in self.READ_TOOLS:
            return self._same_target(req_b, req_a)

        # 网络工具之间：保守串行
        if req_a.name in self.NETWORK_TOOLS and req_b.name in self.NETWORK_TOOLS:
            return True

        return False

    def _same_target(self, write_req: ToolCallRequest, read_req: ToolCallRequest) -> bool:
        """检查写工具和读工具是否操作同一目标"""
        # 提取路径参数
        write_path = write_req.args.get("path") or write_req.args.get("src") or ""
        read_path = read_req.args.get("path") or read_req.args.get("pattern") or ""

        if not write_path or not read_path:
            return False

        # 简化：前缀匹配
        try:
            w = str(write_path).lower().replace("\\", "/").rstrip("/")
            r = str(read_path).lower().replace("\\", "/").rstrip("/")
            return w == r or w.startswith(r + "/") or r.startswith(w + "/")
        except Exception:
            return False


# ============================================================================
# 结果合并器（阶段 S.3）
# ============================================================================

class ResultMerger:
    """并行工具结果合并器

    合并策略：
    - 文本拼接：默认策略，按工具调用顺序拼接
    - 字典合并：结果为 JSON 时合并字段
    - 列表合并：结果为列表时拼接
    - 冲突消解：同名工具按优先级保留
    """

    def merge(
        self,
        results: List[ToolCallResult],
        strategy: str = "concat",
    ) -> str:
        """合并多个工具结果

        Args:
            results: 工具结果列表
            strategy: 合并策略
                - "concat": 文本拼接（默认）
                - "dict": 字典合并（结果需为 JSON）
                - "list": 列表合并
                - "priority": 按优先级保留第一个成功的

        Returns:
            合并后的字符串
        """
        if not results:
            return ""

        if strategy == "priority":
            # 按优先级保留第一个成功的结果
            for r in sorted(results, key=lambda x: -x.priority if hasattr(x, "priority") else 0):
                if r.success:
                    return r.result
            # 全部失败，返回第一个错误
            return results[0].result if results else ""

        if strategy == "list":
            import json
            merged = []
            for r in results:
                try:
                    parsed = json.loads(r.result)
                    if isinstance(parsed, list):
                        merged.extend(parsed)
                    else:
                        merged.append(parsed)
                except (json.JSONDecodeError, TypeError):
                    merged.append(r.result)
            return json.dumps(merged, ensure_ascii=False)

        if strategy == "dict":
            import json
            merged: Dict[str, Any] = {}
            for r in results:
                try:
                    parsed = json.loads(r.result)
                    if isinstance(parsed, dict):
                        merged.update(parsed)
                    else:
                        merged[r.name] = parsed
                except (json.JSONDecodeError, TypeError):
                    merged[r.name] = r.result
            return json.dumps(merged, ensure_ascii=False)

        # 默认 concat
        parts = []
        for r in results:
            if r.success:
                parts.append(f"[{r.name}] {r.result}")
            else:
                parts.append(f"[{r.name} 错误] {r.error or r.result}")
        return "\n\n".join(parts)


# ============================================================================
# 并行工具调度器（阶段 S.1 + S.4）
# ============================================================================

class ParallelToolScheduler:
    """并行工具调度器

    支持单步多工具并行调用，自动分析依赖关系，超时隔离。

    使用方式：
        scheduler = ParallelToolScheduler(tool_map=TOOL_MAP)
        results = await scheduler.execute_parallel([
            ToolCallRequest(name="read_file", args={"path": "a.txt"}),
            ToolCallRequest(name="read_file", args={"path": "b.txt"}),
        ])
        merged = scheduler.merge_results(results)
    """

    def __init__(
        self,
        tool_map: Optional[Dict[str, Callable]] = None,
        max_concurrency: int = 4,
        default_timeout: float = 60.0,
    ):
        """初始化并行调度器

        Args:
            tool_map: 工具映射，None 时从 registry 导入
            max_concurrency: 最大并发数
            default_timeout: 默认超时（秒）
        """
        if tool_map is None:
            try:
                from zeroai.tools.registry import TOOL_MAP
                tool_map = TOOL_MAP
            except ImportError:
                tool_map = {}
        self.tool_map = tool_map
        self.max_concurrency = max(1, max_concurrency)
        self.default_timeout = default_timeout
        self._dependency_graph = ToolDependencyGraph()
        self._merger = ResultMerger()
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    async def execute_single(
        self,
        request: ToolCallRequest,
    ) -> ToolCallResult:
        """执行单个工具调用（带超时和并发控制）"""
        timeout = request.timeout or self.default_timeout
        start_time = time.time()

        async with self._semaphore:
            fn = self.tool_map.get(request.name)
            if fn is None:
                return ToolCallResult(
                    name=request.name,
                    args=request.args,
                    result="",
                    success=False,
                    duration=time.time() - start_time,
                    error=f"未知工具: {request.name}",
                )

            # 过滤无效参数
            try:
                valid_params = set(inspect.signature(fn).parameters)
                safe_args = {k: v for k, v in request.args.items() if k in valid_params}
            except (ValueError, TypeError):
                safe_args = request.args

            try:
                # 执行（支持同步和异步）
                if inspect.iscoroutinefunction(fn):
                    result_value = await asyncio.wait_for(
                        fn(**safe_args),
                        timeout=timeout,
                    )
                else:
                    # 同步函数在线程池中执行，避免阻塞事件循环
                    result_value = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, lambda: fn(**safe_args)
                        ),
                        timeout=timeout,
                    )
                result_str = str(result_value)
                return ToolCallResult(
                    name=request.name,
                    args=request.args,
                    result=result_str,
                    success=True,
                    duration=time.time() - start_time,
                )
            except asyncio.TimeoutError:
                return ToolCallResult(
                    name=request.name,
                    args=request.args,
                    result="",
                    success=False,
                    duration=time.time() - start_time,
                    error=f"工具执行超时（>{timeout}秒）",
                    timed_out=True,
                )
            except TypeError as e:
                return ToolCallResult(
                    name=request.name,
                    args=request.args,
                    result="",
                    success=False,
                    duration=time.time() - start_time,
                    error=f"参数错误: {e}",
                )
            except Exception as e:
                return ToolCallResult(
                    name=request.name,
                    args=request.args,
                    result="",
                    success=False,
                    duration=time.time() - start_time,
                    error=f"{type(e).__name__}: {e}",
                )

    async def execute_parallel(
        self,
        requests: List[ToolCallRequest],
    ) -> List[ToolCallResult]:
        """并行执行多个工具调用

        自动分析依赖关系，无依赖的工具并行，有依赖的串行。

        Args:
            requests: 工具调用请求列表

        Returns:
            工具调用结果列表（顺序与输入对应）
        """
        if not requests:
            return []

        # 单工具直接执行
        if len(requests) == 1:
            return [await self.execute_single(requests[0])]

        # 分析依赖关系，得到执行批次
        batches = self._dependency_graph.analyze_batch(requests)

        results: List[ToolCallResult] = [None] * len(requests)  # type: ignore

        # 按批次执行
        for batch_indices in batches:
            batch_requests = [requests[i] for i in batch_indices]
            # 并行执行当前批次
            batch_results = await asyncio.gather(
                *[self.execute_single(req) for req in batch_requests],
                return_exceptions=False,
            )
            # 按原始索引放回结果
            for idx, result in zip(batch_indices, batch_results):
                results[idx] = result

        return results

    def merge_results(
        self,
        results: List[ToolCallResult],
        strategy: str = "concat",
    ) -> str:
        """合并工具结果"""
        return self._merger.merge(results, strategy=strategy)

    def get_stats(self) -> Dict[str, Any]:
        """获取调度器统计"""
        return {
            "max_concurrency": self.max_concurrency,
            "default_timeout": self.default_timeout,
            "tool_count": len(self.tool_map),
        }


# ============================================================================
# 全局单例
# ============================================================================

_default_scheduler: Optional[ParallelToolScheduler] = None


def get_parallel_scheduler() -> ParallelToolScheduler:
    """获取全局并行调度器单例"""
    global _default_scheduler
    if _default_scheduler is None:
        _default_scheduler = ParallelToolScheduler()
    return _default_scheduler


def reset_parallel_scheduler() -> None:
    """重置全局并行调度器"""
    global _default_scheduler
    _default_scheduler = None


__all__ = [
    "ToolCallRequest",
    "ToolCallResult",
    "ToolDependencyGraph",
    "ResultMerger",
    "ParallelToolScheduler",
    "get_parallel_scheduler",
    "reset_parallel_scheduler",
]
