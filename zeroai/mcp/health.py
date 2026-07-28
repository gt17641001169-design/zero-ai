"""MCP 健康检查与自动重连机制（阶段 F.3）

本模块为 MCPClient 增加健康检查和自动重连能力，不修改原有 client.py 代码，
通过外部包装器方式注入重连逻辑。

设计原则（阶段 F.3）：
- 增量追加：不修改 client.py，通过组合方式增强
- 指数退避：连接失败时按 1s/2s/4s/8s/16s 退避重试（最多 5 次）
- 健康检查：ping 探测 + 工具列表验证
- 状态追踪：记录每个服务器的历史健康状态
- 优雅降级：重连失败后标记为 degraded，不阻塞其他服务器

使用方式：
    from zeroai.mcp.health import MCPHealthMonitor, get_health_monitor
    monitor = get_health_monitor()
    await monitor.check_all()  # 检查所有已注册服务器的健康状态
    report = monitor.get_health_report()  # 获取健康报告
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .client import MCPClient, MCPClientError
from .registry import get_mcp_registry


# ============================================================================
# 健康状态数据结构
# ============================================================================

@dataclass
class HealthRecord:
    """单个服务器的健康记录"""
    server_name: str
    is_healthy: bool = False
    last_check_time: float = 0.0
    last_success_time: float = 0.0
    last_failure_time: float = 0.0
    failure_count: int = 0
    success_count: int = 0
    consecutive_failures: int = 0
    last_error: str = ""
    reconnect_attempts: int = 0
    is_degraded: bool = False  # 多次重连失败后标记为降级
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "server_name": self.server_name,
            "is_healthy": self.is_healthy,
            "is_degraded": self.is_degraded,
            "last_check_time": self.last_check_time,
            "last_success_time": self.last_success_time,
            "last_failure_time": self.last_failure_time,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "reconnect_attempts": self.reconnect_attempts,
            "history": self.history[-10:],  # 只保留最近 10 条
        }


# ============================================================================
# 重连策略
# ============================================================================

@dataclass
class ReconnectPolicy:
    """重连策略配置"""
    max_attempts: int = 5
    initial_delay: float = 1.0  # 首次重连延迟 1 秒
    max_delay: float = 60.0     # 最大延迟 60 秒
    backoff_factor: float = 2.0  # 指数退避因子
    degrade_threshold: int = 5  # 连续失败次数达到此值后标记为降级

    def get_delay(self, attempt: int) -> float:
        """计算第 N 次重连的延迟时间（指数退避）"""
        delay = self.initial_delay * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)


# ============================================================================
# 健康监控器
# ============================================================================

class MCPHealthMonitor:
    """MCP 服务器健康监控器

    单例模式，监控所有已注册的 MCP 服务器。
    """

    def __init__(self, policy: Optional[ReconnectPolicy] = None):
        self._policy = policy or ReconnectPolicy()
        self._records: Dict[str, HealthRecord] = {}
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None
        self._monitoring = False
        self._check_interval = 60.0  # 默认 60 秒检查一次

    @property
    def policy(self) -> ReconnectPolicy:
        return self._policy

    @property
    def is_monitoring(self) -> bool:
        return self._monitoring

    def get_record(self, server_name: str) -> HealthRecord:
        """获取服务器健康记录（不存在则创建）"""
        if server_name not in self._records:
            self._records[server_name] = HealthRecord(server_name=server_name)
        return self._records[server_name]

    async def check_server(self, server_name: str) -> bool:
        """检查单个服务器健康状态

        通过 ping 探测和工具列表验证来判断健康状态。

        Args:
            server_name: 服务器名称

        Returns:
            True 健康，False 不健康
        """
        registry = get_mcp_registry()
        client = registry.get_client(server_name)
        record = self.get_record(server_name)

        async with self._lock:
            record.last_check_time = time.time()

            if client is None:
                record.is_healthy = False
                record.last_error = "客户端未注册"
                record.consecutive_failures += 1
                record.failure_count += 1
                record.last_failure_time = time.time()
                self._add_history(record, False, "客户端未注册")
                return False

            try:
                # 检查连接状态
                if not client.is_connected:
                    # 尝试重连
                    reconnected = await self._reconnect_with_backoff(client, record)
                    if not reconnected:
                        return False

                # ping 探测
                ping_ok = await self._ping(client)
                if not ping_ok:
                    record.is_healthy = False
                    record.last_error = "ping 失败"
                    record.consecutive_failures += 1
                    record.failure_count += 1
                    record.last_failure_time = time.time()
                    self._add_history(record, False, "ping 失败")
                    return False

                # 工具列表验证（确保工具缓存有效）
                try:
                    tools = await client.list_tools()
                    if not tools and tools is not None:
                        # 工具列表为空可能是服务器异常
                        record.is_healthy = False
                        record.last_error = "工具列表为空"
                        record.consecutive_failures += 1
                        record.failure_count += 1
                        record.last_failure_time = time.time()
                        self._add_history(record, False, "工具列表为空")
                        return False
                except Exception as e:
                    # 工具列表获取失败，但 ping 成功，标记为亚健康
                    record.is_healthy = True
                    record.last_error = f"工具列表获取失败: {e}"
                    record.success_count += 1
                    record.consecutive_failures = 0
                    record.last_success_time = time.time()
                    self._add_history(record, True, f"ping OK 但工具列表失败: {e}")
                    return True

                # 完全健康
                record.is_healthy = True
                record.last_error = ""
                record.success_count += 1
                record.consecutive_failures = 0
                record.last_success_time = time.time()
                record.is_degraded = False
                self._add_history(record, True, "健康")
                return True

            except asyncio.TimeoutError:
                record.is_healthy = False
                record.last_error = "健康检查超时"
                record.consecutive_failures += 1
                record.failure_count += 1
                record.last_failure_time = time.time()
                self._add_history(record, False, "超时")
                return False
            except Exception as e:
                record.is_healthy = False
                record.last_error = str(e)
                record.consecutive_failures += 1
                record.failure_count += 1
                record.last_failure_time = time.time()
                self._add_history(record, False, str(e))
                return False

    async def check_all(self) -> Dict[str, bool]:
        """检查所有已注册服务器的健康状态

        Returns:
            {server_name: is_healthy}
        """
        registry = get_mcp_registry()
        clients = registry.clients
        results: Dict[str, bool] = {}

        # 并发检查所有服务器
        tasks = [self.check_server(name) for name in clients.keys()]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for name, outcome in zip(clients.keys(), outcomes):
            if isinstance(outcome, Exception):
                results[name] = False
                record = self.get_record(name)
                record.is_healthy = False
                record.last_error = str(outcome)
                record.consecutive_failures += 1
                record.failure_count += 1
                record.last_failure_time = time.time()
                self._add_history(record, False, f"异常: {outcome}")
            else:
                results[name] = bool(outcome)

        return results

    async def _reconnect_with_backoff(
        self,
        client: MCPClient,
        record: HealthRecord,
    ) -> bool:
        """指数退避重连

        Args:
            client: MCP 客户端
            record: 健康记录

        Returns:
            True 重连成功，False 失败
        """
        policy = self._policy

        for attempt in range(policy.max_attempts):
            record.reconnect_attempts += 1
            delay = policy.get_delay(attempt)

            if attempt > 0:
                await asyncio.sleep(delay)

            try:
                await client.connect()
                record.is_degraded = False
                return True
            except Exception as e:
                record.last_error = f"重连失败 (尝试 {attempt + 1}/{policy.max_attempts}): {e}"
                continue

        # 达到最大重连次数，标记为降级
        if record.consecutive_failures >= policy.degrade_threshold:
            record.is_degraded = True

        return False

    async def _ping(self, client: MCPClient) -> bool:
        """ping 探测服务器

        Args:
            client: MCP 客户端

        Returns:
            True ping 成功，False 失败
        """
        try:
            # 使用 5 秒超时的 ping
            await asyncio.wait_for(client.ping(), timeout=5.0)
            return True
        except asyncio.TimeoutError:
            return False
        except Exception:
            return False

    def _add_history(self, record: HealthRecord, success: bool, msg: str) -> None:
        """添加历史记录（最多保留 100 条）"""
        record.history.append({
            "time": time.time(),
            "success": success,
            "message": msg,
        })
        if len(record.history) > 100:
            record.history = record.history[-100:]

    def get_health_report(self) -> Dict[str, Any]:
        """获取健康报告

        Returns:
            {
                "total_servers": int,
                "healthy": int,
                "unhealthy": int,
                "degraded": int,
                "servers": {name: record.to_dict()}
            }
        """
        total = len(self._records)
        healthy = sum(1 for r in self._records.values() if r.is_healthy)
        unhealthy = total - healthy
        degraded = sum(1 for r in self._records.values() if r.is_degraded)

        return {
            "total_servers": total,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "degraded": degraded,
            "servers": {name: r.to_dict() for name, r in self._records.items()},
        }

    async def start_monitoring(self, interval: float = 60.0) -> None:
        """启动后台健康监控

        Args:
            interval: 检查间隔（秒）
        """
        if self._monitoring:
            return
        self._monitoring = True
        self._check_interval = interval
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop_monitoring(self) -> None:
        """停止后台健康监控"""
        self._monitoring = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

    async def _monitor_loop(self) -> None:
        """后台监控循环"""
        while self._monitoring:
            try:
                await self.check_all()
            except Exception:
                pass
            await asyncio.sleep(self._check_interval)

    def reset(self) -> None:
        """重置所有健康记录"""
        self._records.clear()


# ============================================================================
# 全局单例
# ============================================================================

_health_monitor: Optional[MCPHealthMonitor] = None


def get_health_monitor(policy: Optional[ReconnectPolicy] = None) -> MCPHealthMonitor:
    """获取全局健康监控器实例

    Args:
        policy: 重连策略（仅首次创建时生效）

    Returns:
        MCPHealthMonitor 实例
    """
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = MCPHealthMonitor(policy=policy)
    return _health_monitor


def reset_health_monitor() -> None:
    """重置全局健康监控器（主要用于测试）"""
    global _health_monitor
    if _health_monitor is not None:
        _health_monitor.reset()
    _health_monitor = None


__all__ = [
    "HealthRecord",
    "ReconnectPolicy",
    "MCPHealthMonitor",
    "get_health_monitor",
    "reset_health_monitor",
]
