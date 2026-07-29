"""多 Agent 消息总线（阶段 O.1）

提供 Agent 间通信能力，支持发布/订阅模式和共享黑板系统：

1. 消息总线（MessageBus）：Agent 间发布/订阅消息
   - 主题（topic） based 的发布订阅
   - 支持同步和异步订阅者
   - 消息历史记录

2. 共享黑板（Blackboard）：所有 Agent 共享的状态空间
   - 键值对存储，支持版本控制
   - 观察者模式，值变化时通知订阅者
   - 分区隔离（namespace），避免冲突

3. Agent 通信协议：标准化的消息格式
   - 发送者/接收者/主题/内容/元数据
   - 消息类型：command / query / response / notification

使用方式：
    bus = get_message_bus()
    # 订阅
    bus.subscribe("analysis_result", my_handler)
    # 发布
    bus.publish("analysis_result", {"data": 123})
    # 黑板
    board = get_blackboard()
    board.write("namespace1", "key", "value")
    val = board.read("namespace1", "key")
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


# ============================================================================
# 消息数据结构
# ============================================================================

@dataclass
class AgentMessage:
    """Agent 间消息"""

    sender: str                              # 发送者 Agent ID
    receiver: Optional[str] = None           # 接收者 Agent ID（None 表示广播）
    topic: str = ""                          # 消息主题
    content: Any = None                      # 消息内容
    msg_type: str = "notification"           # 消息类型：command/query/response/notification
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    reply_to: Optional[str] = None           # 回复的消息 ID

    def to_dict(self) -> Dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "sender": self.sender,
            "receiver": self.receiver,
            "topic": self.topic,
            "content": self.content,
            "msg_type": self.msg_type,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "reply_to": self.reply_to,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentMessage":
        return cls(
            sender=d.get("sender", ""),
            receiver=d.get("receiver"),
            topic=d.get("topic", ""),
            content=d.get("content"),
            msg_type=d.get("msg_type", "notification"),
            metadata=d.get("metadata", {}),
            msg_id=d.get("msg_id", str(uuid.uuid4())),
            timestamp=d.get("timestamp", time.time()),
            reply_to=d.get("reply_to"),
        )


# ============================================================================
# 消息总线（阶段 O.1.1）
# ============================================================================

# 订阅者类型：同步或异步函数
Subscriber = Callable[[AgentMessage], Union[None, Any]]


class MessageBus:
    """消息总线：Agent 间发布/订阅通信

    特性：
    - 主题 based 发布订阅
    - 支持同步和异步订阅者
    - 消息历史记录（可配置容量）
    - 线程安全

    使用方式：
        bus = MessageBus()
        bus.subscribe("topic1", handler)
        bus.publish("topic1", message)
    """

    def __init__(self, max_history: int = 1000):
        """初始化

        Args:
            max_history: 消息历史记录最大数量
        """
        self._subscribers: Dict[str, List[Subscriber]] = {}
        self._history: List[AgentMessage] = []
        self._max_history = max_history
        self._lock = threading.RLock()
        self._agent_registry: Dict[str, Dict[str, Any]] = {}

    def subscribe(
        self,
        topic: str,
        handler: Subscriber,
    ) -> Callable[[], None]:
        """订阅主题

        Args:
            topic: 主题名
            handler: 消息处理函数（同步或异步）

        Returns:
            取消订阅函数
        """
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(handler)

        def _unsubscribe():
            with self._lock:
                if topic in self._subscribers:
                    try:
                        self._subscribers[topic].remove(handler)
                    except ValueError:
                        pass

        return _unsubscribe

    def unsubscribe(
        self,
        topic: str,
        handler: Subscriber,
    ) -> bool:
        """取消订阅

        Returns:
            是否成功取消
        """
        with self._lock:
            if topic in self._subscribers:
                try:
                    self._subscribers[topic].remove(handler)
                    return True
                except ValueError:
                    pass
        return False

    def publish(
        self,
        message: AgentMessage,
        async_dispatch: bool = True,
    ) -> int:
        """发布消息

        Args:
            message: 待发布消息
            async_dispatch: 是否异步分发（True 时异步订阅者用 asyncio.create_task）

        Returns:
            分发到的订阅者数量
        """
        # 记录历史
        with self._lock:
            self._history.append(message)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            subscribers = list(self._subscribers.get(message.topic, []))

        # 分发消息
        count = 0
        for handler in subscribers:
            try:
                # 检查接收者过滤
                if message.receiver and message.receiver != self._get_handler_agent_id(handler):
                    continue

                result = handler(message)
                # 如果是协程，尝试调度
                if asyncio.iscoroutine(result):
                    if async_dispatch:
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.ensure_future(result)
                            else:
                                loop.run_until_complete(result)
                        except RuntimeError:
                            # 无事件循环，创建新线程运行
                            import threading
                            t = threading.Thread(
                                target=lambda: asyncio.run(result),
                                daemon=True,
                            )
                            t.start()
                    else:
                        # 同步执行协程
                        try:
                            loop = asyncio.new_event_loop()
                            loop.run_until_complete(result)
                            loop.close()
                        except Exception:
                            pass
                count += 1
            except Exception:
                pass  # 订阅者异常不影响其他订阅者

        return count

    def publish_simple(
        self,
        sender: str,
        topic: str,
        content: Any,
        receiver: Optional[str] = None,
        msg_type: str = "notification",
    ) -> int:
        """便捷发布方法

        Args:
            sender: 发送者 ID
            topic: 主题
            content: 内容
            receiver: 接收者 ID（None 广播）
            msg_type: 消息类型

        Returns:
            分发数量
        """
        msg = AgentMessage(
            sender=sender,
            receiver=receiver,
            topic=topic,
            content=content,
            msg_type=msg_type,
        )
        return self.publish(msg)

    def register_agent(
        self,
        agent_id: str,
        agent_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """注册 Agent

        Args:
            agent_id: Agent 唯一标识
            agent_info: Agent 信息（角色、能力等）
        """
        with self._lock:
            self._agent_registry[agent_id] = agent_info or {}

    def unregister_agent(self, agent_id: str) -> None:
        """注销 Agent"""
        with self._lock:
            self._agent_registry.pop(agent_id, None)

    def get_registered_agents(self) -> Dict[str, Dict[str, Any]]:
        """获取已注册的 Agent"""
        with self._lock:
            return dict(self._agent_registry)

    def get_history(
        self,
        topic: Optional[str] = None,
        limit: int = 100,
    ) -> List[AgentMessage]:
        """获取消息历史

        Args:
            topic: 主题过滤（None 表示所有）
            limit: 最大返回数量

        Returns:
            消息列表（按时间倒序）
        """
        with self._lock:
            if topic:
                msgs = [m for m in self._history if m.topic == topic]
            else:
                msgs = list(self._history)
        return list(reversed(msgs[-limit:]))

    def clear_history(self) -> None:
        """清空历史"""
        with self._lock:
            self._history.clear()

    @staticmethod
    def _get_handler_agent_id(handler: Subscriber) -> Optional[str]:
        """从 handler 获取关联的 Agent ID"""
        return getattr(handler, "_agent_id", None)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "topics": list(self._subscribers.keys()),
                "total_subscribers": sum(len(v) for v in self._subscribers.values()),
                "history_size": len(self._history),
                "registered_agents": len(self._agent_registry),
            }


# ============================================================================
# 共享黑板系统（阶段 O.1.2）
# ============================================================================

class Blackboard:
    """共享黑板：所有 Agent 共享的状态空间

    特性：
    - 键值对存储，支持命名空间隔离
    - 版本控制，每次写入递增版本号
    - 观察者模式，值变化时通知订阅者
    - 历史记录（可配置容量）

    使用方式：
        board = Blackboard()
        board.write("analysis", "result", {"data": 123})
        val = board.read("analysis", "result")
        board.subscribe("analysis", "result", handler)
    """

    def __init__(self, max_history_per_key: int = 50):
        """初始化

        Args:
            max_history_per_key: 每个 key 的历史记录最大数量
        """
        self._data: Dict[str, Dict[str, Any]] = {}  # namespace -> key -> value
        self._versions: Dict[str, Dict[str, int]] = {}  # namespace -> key -> version
        self._history: Dict[str, Dict[str, List[Tuple[int, Any, float]]]] = {}
        self._observers: Dict[str, Dict[str, List[Callable]]] = {}
        self._lock = threading.RLock()
        self._max_history = max_history_per_key

    def write(
        self,
        namespace: str,
        key: str,
        value: Any,
        writer: str = "",
    ) -> int:
        """写入值

        Args:
            namespace: 命名空间
            key: 键
            value: 值
            writer: 写入者 Agent ID

        Returns:
            新版本号
        """
        with self._lock:
            # 初始化命名空间
            if namespace not in self._data:
                self._data[namespace] = {}
                self._versions[namespace] = {}
                self._history[namespace] = {}
                self._observers[namespace] = {}

            # 递增版本号
            old_version = self._versions[namespace].get(key, 0)
            new_version = old_version + 1
            self._versions[namespace][key] = new_version

            # 存储值
            self._data[namespace][key] = value

            # 记录历史
            if key not in self._history[namespace]:
                self._history[namespace][key] = []
            self._history[namespace][key].append((new_version, value, time.time()))
            if len(self._history[namespace][key]) > self._max_history:
                self._history[namespace][key] = self._history[namespace][key][-self._max_history:]

            # 收集观察者
            observers = list(self._observers[namespace].get(key, []))

        # 通知观察者（在锁外执行，避免死锁）
        for observer in observers:
            try:
                result = observer(value, new_version, writer)
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(result)
                    except RuntimeError:
                        pass
            except Exception:
                pass

        return new_version

    def read(
        self,
        namespace: str,
        key: str,
        default: Any = None,
    ) -> Any:
        """读取值

        Args:
            namespace: 命名空间
            key: 键
            default: 默认值（key 不存在时返回）

        Returns:
            值
        """
        with self._lock:
            if namespace in self._data and key in self._data[namespace]:
                return self._data[namespace][key]
        return default

    def get_version(self, namespace: str, key: str) -> int:
        """获取当前版本号"""
        with self._lock:
            return self._versions.get(namespace, {}).get(key, 0)

    def get_history(
        self,
        namespace: str,
        key: str,
        limit: int = 10,
    ) -> List[Tuple[int, Any, float]]:
        """获取 key 的历史记录

        Returns:
            [(version, value, timestamp), ...]
        """
        with self._lock:
            history = self._history.get(namespace, {}).get(key, [])
            return list(reversed(history[-limit:]))

    def subscribe(
        self,
        namespace: str,
        key: str,
        observer: Callable[[Any, int, str], None],
    ) -> Callable[[], None]:
        """订阅 key 的变化

        Args:
            namespace: 命名空间
            key: 键
            observer: 观察者函数 (value, version, writer) -> None

        Returns:
            取消订阅函数
        """
        with self._lock:
            if namespace not in self._observers:
                self._observers[namespace] = {}
            if key not in self._observers[namespace]:
                self._observers[namespace][key] = []
            self._observers[namespace][key].append(observer)

        def _unsubscribe():
            with self._lock:
                if namespace in self._observers and key in self._observers[namespace]:
                    try:
                        self._observers[namespace][key].remove(observer)
                    except ValueError:
                        pass

        return _unsubscribe

    def list_keys(self, namespace: str) -> List[str]:
        """列出命名空间下的所有 key"""
        with self._lock:
            return list(self._data.get(namespace, {}).keys())

    def list_namespaces(self) -> List[str]:
        """列出所有命名空间"""
        with self._lock:
            return list(self._data.keys())

    def delete(self, namespace: str, key: str) -> bool:
        """删除 key"""
        with self._lock:
            if namespace in self._data and key in self._data[namespace]:
                del self._data[namespace][key]
                self._versions.get(namespace, {}).pop(key, None)
                return True
        return False

    def clear_namespace(self, namespace: str) -> int:
        """清空命名空间

        Returns:
            清空的 key 数量
        """
        with self._lock:
            count = len(self._data.get(namespace, {}))
            self._data.pop(namespace, None)
            self._versions.pop(namespace, None)
            self._history.pop(namespace, None)
            self._observers.pop(namespace, None)
            return count

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "namespaces": len(self._data),
                "total_keys": sum(len(v) for v in self._data.values()),
                "total_observers": sum(
                    len(keys) for ns in self._observers.values()
                    for keys in ns.values()
                ),
            }


# ============================================================================
# 单例管理
# ============================================================================

_message_bus: Optional[MessageBus] = None
_blackboard: Optional[Blackboard] = None


def get_message_bus() -> MessageBus:
    """获取全局消息总线单例"""
    global _message_bus
    if _message_bus is None:
        _message_bus = MessageBus()
    return _message_bus


def get_blackboard() -> Blackboard:
    """获取全局共享黑板单例"""
    global _blackboard
    if _blackboard is None:
        _blackboard = Blackboard()
    return _blackboard


def reset_message_bus() -> None:
    """重置消息总线"""
    global _message_bus
    _message_bus = None


def reset_blackboard() -> None:
    """重置黑板"""
    global _blackboard
    _blackboard = None


__all__ = [
    "AgentMessage",
    "MessageBus",
    "Blackboard",
    "get_message_bus",
    "get_blackboard",
    "reset_message_bus",
    "reset_blackboard",
]
