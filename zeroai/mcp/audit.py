"""MCP 工具调用审计日志（阶段 F.4）

记录所有 MCP 工具调用的详细信息，用于：
1. 安全审计：追踪谁在什么时候调用了什么工具
2. 性能分析：统计工具调用耗时和成功率
3. 故障排查：定位工具调用失败的根因
4. 使用模式分析：识别高频工具和参数模式

设计原则（阶段 F.4）：
- 增量追加：不修改 registry.py，通过装饰器方式注入
- 双写日志：内存缓冲区 + 磁盘持久化
- 大小限制：内存最多 1000 条，磁盘按日期轮转
- 敏感数据脱敏：参数中的 api_key/password/token 自动脱敏
- 异步写入：不阻塞工具调用主流程

使用方式：
    from zeroai.mcp.audit import get_audit_logger, audit_mcp_call
    logger = get_audit_logger()
    # 自动记录：包装函数已通过 audit_mcp_call 装饰
    # 手动查询：
    records = logger.query_records(server_name="filesystem")
    stats = logger.get_statistics()
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ============================================================================
# 审计记录数据结构
# ============================================================================

@dataclass
class AuditRecord:
    """单次工具调用的审计记录"""
    timestamp: float
    server_name: str
    tool_name: str
    full_tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    success: bool = False
    duration: float = 0.0  # 秒
    result_length: int = 0
    error_message: str = ""
    result_preview: str = ""  # 结果前 200 字符（脱敏后）
    caller: str = ""  # 调用来源（如 agent_loop / user_direct）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json_line(self) -> str:
        """转换为 JSONL 格式（一行一条）"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ============================================================================
# 敏感数据脱敏
# ============================================================================

# 敏感字段名模式
_SENSITIVE_KEY_PATTERNS = re.compile(
    r"(?i)(api_key|apikey|api-key|password|passwd|pwd|token|secret|"
    r"access_key|accesskey|private_key|privatekey|bearer|authorization|auth)"
)

# 敏感值模式（长字符串、密钥格式）
_SENSITIVE_VALUE_PATTERNS = re.compile(
    r"(?i)(sk-[a-zA-Z0-9]{20,}|Bearer\s+[A-Za-z0-9\-\._~+\/=]+|"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----)"
)


def _sanitize_value(value: Any, key: str = "") -> Any:
    """脱敏单个值"""
    if isinstance(value, str):
        # 1. 字段名匹配
        if key and _SENSITIVE_KEY_PATTERNS.search(key):
            if len(value) > 8:
                return value[:4] + "***" + value[-4:]
            return "***"
        # 2. 值模式匹配
        if _SENSITIVE_VALUE_PATTERNS.search(value):
            if len(value) > 8:
                return value[:4] + "***" + value[-4:]
            return "***"
        return value
    elif isinstance(value, dict):
        return {k: _sanitize_value(v, k) for k, v in value.items()}
    elif isinstance(value, list):
        return [_sanitize_value(v, key) for v in value]
    return value


def _sanitize_arguments(args: Dict[str, Any]) -> Dict[str, Any]:
    """脱敏参数字典"""
    return {k: _sanitize_value(v, k) for k, v in args.items()}


def _sanitize_result(text: str) -> str:
    """脱敏结果文本"""
    if not text:
        return ""
    # 替换敏感值模式
    sanitized = _SENSITIVE_VALUE_PATTERNS.sub("***REDACTED***", text)
    return sanitized


# ============================================================================
# 审计日志器
# ============================================================================

class MCPAuditLogger:
    """MCP 工具调用审计日志器

    单例模式，双写日志（内存 + 磁盘）。
    """

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        max_memory_records: int = 1000,
        max_file_size_mb: float = 10.0,
    ):
        self._log_dir = log_dir or (Path.home() / ".zeroai" / "mcp_audit")
        self._max_memory = max_memory_records
        self._max_file_size = int(max_file_size_mb * 1024 * 1024)
        self._buffer: deque = deque(maxlen=max_memory_records)
        self._write_lock = asyncio.Lock()
        self._current_file: Optional[Path] = None
        self._current_size = 0

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    def record(
        self,
        server_name: str,
        tool_name: str,
        full_tool_name: str,
        arguments: Dict[str, Any],
        success: bool,
        duration: float,
        result_length: int = 0,
        error_message: str = "",
        result_preview: str = "",
        caller: str = "",
    ) -> AuditRecord:
        """记录一次工具调用

        Args:
            server_name: MCP 服务器名
            tool_name: 原始工具名
            full_tool_name: 完整工具名（含 mcp__ 前缀）
            arguments: 调用参数（会自动脱敏）
            success: 是否成功
            duration: 耗时（秒）
            result_length: 结果长度
            error_message: 错误信息
            result_preview: 结果预览（会自动脱敏）
            caller: 调用来源

        Returns:
            AuditRecord 实例
        """
        record = AuditRecord(
            timestamp=time.time(),
            server_name=server_name,
            tool_name=tool_name,
            full_tool_name=full_tool_name,
            arguments=_sanitize_arguments(arguments),
            success=success,
            duration=round(duration, 3),
            result_length=result_length,
            error_message=error_message[:500] if error_message else "",
            result_preview=_sanitize_result(result_preview)[:200],
            caller=caller,
        )

        # 写入内存缓冲区
        self._buffer.append(record)

        # 异步写入磁盘（不阻塞）
        try:
            asyncio.ensure_future(self._write_to_disk(record))
        except RuntimeError:
            # 没有事件循环（同步上下文），跳过磁盘写入
            pass

        return record

    async def _write_to_disk(self, record: AuditRecord) -> None:
        """异步写入磁盘"""
        async with self._write_lock:
            try:
                self._log_dir.mkdir(parents=True, exist_ok=True)
                date_str = time.strftime("%Y-%m-%d", time.localtime(record.timestamp))
                log_file = self._log_dir / f"mcp_audit_{date_str}.jsonl"

                # 检查文件大小，超过阈值则轮转
                if log_file.exists():
                    size = log_file.stat().st_size
                    if size > self._max_file_size:
                        # 轮转：重命名为带时间戳的备份
                        timestamp_str = time.strftime(
                            "%Y%m%d_%H%M%S", time.localtime(record.timestamp)
                        )
                        backup = self._log_dir / f"mcp_audit_{date_str}_{timestamp_str}.jsonl"
                        log_file.rename(backup)

                # 追加写入
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(record.to_json_line() + "\n")
            except Exception:
                pass  # 磁盘写入失败不影响主流程

    def query_records(
        self,
        server_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        success: Optional[bool] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        limit: int = 100,
    ) -> List[AuditRecord]:
        """查询审计记录

        Args:
            server_name: 按服务器名过滤
            tool_name: 按工具名过滤
            success: 按成功/失败过滤
            since: 起始时间戳
            until: 结束时间戳
            limit: 最多返回条数

        Returns:
            审计记录列表（按时间倒序）
        """
        results = []
        for record in reversed(self._buffer):
            if server_name and record.server_name != server_name:
                continue
            if tool_name and record.tool_name != tool_name:
                continue
            if success is not None and record.success != success:
                continue
            if since and record.timestamp < since:
                continue
            if until and record.timestamp > until:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

    def get_statistics(self, hours: float = 24.0) -> Dict[str, Any]:
        """获取统计信息

        Args:
            hours: 统计最近 N 小时的数据

        Returns:
            统计信息字典
        """
        cutoff = time.time() - hours * 3600
        recent = [r for r in self._buffer if r.timestamp >= cutoff]

        total = len(recent)
        success_count = sum(1 for r in recent if r.success)
        fail_count = total - success_count

        # 按服务器分组统计
        by_server: Dict[str, Dict[str, int]] = {}
        by_tool: Dict[str, Dict[str, int]] = {}

        for r in recent:
            # 服务器统计
            if r.server_name not in by_server:
                by_server[r.server_name] = {"total": 0, "success": 0, "fail": 0}
            by_server[r.server_name]["total"] += 1
            if r.success:
                by_server[r.server_name]["success"] += 1
            else:
                by_server[r.server_name]["fail"] += 1

            # 工具统计
            if r.full_tool_name not in by_tool:
                by_tool[r.full_tool_name] = {"total": 0, "success": 0, "fail": 0, "avg_duration": 0.0}
            by_tool[r.full_tool_name]["total"] += 1
            if r.success:
                by_tool[r.full_tool_name]["success"] += 1
            else:
                by_tool[r.full_tool_name]["fail"] += 1

        # 计算平均耗时
        for tool_name, stats in by_tool.items():
            durations = [r.duration for r in recent if r.full_tool_name == tool_name]
            if durations:
                stats["avg_duration"] = round(sum(durations) / len(durations), 3)

        # 平均耗时
        avg_duration = (
            round(sum(r.duration for r in recent) / total, 3) if total > 0 else 0.0
        )

        return {
            "period_hours": hours,
            "total_calls": total,
            "success_count": success_count,
            "fail_count": fail_count,
            "success_rate": round(success_count / total, 4) if total > 0 else 0.0,
            "avg_duration": avg_duration,
            "by_server": by_server,
            "by_tool": by_tool,
        }

    def clear_memory(self) -> None:
        """清空内存缓冲区"""
        self._buffer.clear()

    def export_records(
        self,
        output_path: Path,
        server_name: Optional[str] = None,
        since: Optional[float] = None,
    ) -> int:
        """导出审计记录到文件

        Args:
            output_path: 输出文件路径
            server_name: 按服务器名过滤（None 表示全部）
            since: 起始时间戳

        Returns:
            导出的记录数
        """
        records = self.query_records(server_name=server_name, since=since, limit=10000)
        with open(output_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(record.to_json_line() + "\n")
        return len(records)


# ============================================================================
# 装饰器：为 MCP 工具包装函数添加审计
# ============================================================================

def audit_mcp_call(
    server_name: str,
    tool_name: str,
    full_tool_name: str,
    logger: Optional[MCPAuditLogger] = None,
) -> Callable:
    """装饰器：为 MCP 工具包装函数添加审计日志

    Args:
        server_name: 服务器名
        tool_name: 工具名
        full_tool_name: 完整工具名
        logger: 审计日志器（None 表示使用全局实例）

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(**kwargs: Any) -> str:
            audit = logger or get_audit_logger()
            start_time = time.time()
            success = False
            error_msg = ""
            result_text = ""

            try:
                result = await func(**kwargs)
                result_text = result if isinstance(result, str) else str(result)
                # 判断成功：不包含错误标记
                success = not any(
                    marker in result_text
                    for marker in ["[MCP 工具错误]", "[MCP 连接错误]", "[MCP 超时]", "[MCP 异常]"]
                )
                if not success:
                    error_msg = result_text[:200]
                return result
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                success = False
                raise
            finally:
                duration = time.time() - start_time
                audit.record(
                    server_name=server_name,
                    tool_name=tool_name,
                    full_tool_name=full_tool_name,
                    arguments=kwargs,
                    success=success,
                    duration=duration,
                    result_length=len(result_text),
                    error_message=error_msg,
                    result_preview=result_text[:200],
                    caller="agent_loop",
                )

        # 保留原函数的元数据
        wrapper.__name__ = full_tool_name
        wrapper.__qualname__ = full_tool_name
        wrapper.__doc__ = f"[审计] {func.__doc__ or ''}"
        return wrapper
    return decorator


# ============================================================================
# 全局单例
# ============================================================================

_audit_logger: Optional[MCPAuditLogger] = None


def get_audit_logger() -> MCPAuditLogger:
    """获取全局审计日志器实例"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = MCPAuditLogger()
    return _audit_logger


def reset_audit_logger() -> None:
    """重置全局审计日志器（主要用于测试）"""
    global _audit_logger
    if _audit_logger is not None:
        _audit_logger.clear_memory()
    _audit_logger = None


__all__ = [
    "AuditRecord",
    "MCPAuditLogger",
    "audit_mcp_call",
    "get_audit_logger",
    "reset_audit_logger",
]
