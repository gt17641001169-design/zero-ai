"""Agent Loop 持久化与断点续跑（阶段 G.2）

为 AdvancedAgentLoop 增加思维链持久化和断点续跑能力：
1. 思维链序列化：将 Thought 链保存到磁盘（JSON 格式）
2. 断点续跑：从持久化的思维链最后一步恢复执行
3. 会话管理：每个任务一个独立会话 ID

设计原则：
- 增量追加：不修改 agent.py 原有代码
- 可选启用：通过参数控制是否启用持久化
- 向后兼容：无持久化文件时按原有流程执行

使用方式：
    from zeroai.core.agent_persistence import AgentPersistence
    persistence = AgentPersistence(session_id="task_001")
    # 保存思维链
    persistence.save_chain(thought_chain, messages)
    # 加载并续跑
    state = persistence.load_chain()
    if state:
        thought_chain = state["thought_chain"]
        messages = state["messages"]
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================================
# 持久化数据结构
# ============================================================================

@dataclass
class ThoughtSnapshot:
    """思维节点的持久化快照（与 Thought dataclass 解耦）"""
    step: int
    thought: str
    action_type: str
    tool_name: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    reflection: Optional[str] = None
    success: bool = True
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ThoughtSnapshot":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AgentSession:
    """Agent 会话状态"""
    session_id: str
    task: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    thought_chain: List[ThoughtSnapshot] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    is_completed: bool = False
    is_paused: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task": self.task,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "thought_chain": [t.to_dict() for t in self.thought_chain],
            "messages": self.messages,
            "is_completed": self.is_completed,
            "is_paused": self.is_paused,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentSession":
        return cls(
            session_id=d["session_id"],
            task=d.get("task", ""),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            thought_chain=[
                ThoughtSnapshot.from_dict(t) for t in d.get("thought_chain", [])
            ],
            messages=d.get("messages", []),
            is_completed=d.get("is_completed", False),
            is_paused=d.get("is_paused", False),
            metadata=d.get("metadata", {}),
        )


# ============================================================================
# 持久化管理器
# ============================================================================

class AgentPersistence:
    """Agent 思维链持久化管理器

    每个会话一个 JSON 文件，存储在 ~/.zeroai/agent_sessions/
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        storage_dir: Optional[Path] = None,
    ):
        self.session_id = session_id or self._generate_session_id()
        self._storage_dir = storage_dir or (Path.home() / ".zeroai" / "agent_sessions")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._session: Optional[AgentSession] = None

    @property
    def storage_dir(self) -> Path:
        return self._storage_dir

    @property
    def session_file(self) -> Path:
        return self._storage_dir / f"{self.session_id}.json"

    @staticmethod
    def _generate_session_id() -> str:
        """生成唯一会话 ID"""
        return f"session_{int(time.time())}_{uuid.uuid4().hex[:8]}"

    def save_chain(
        self,
        thought_chain: List[Any],
        messages: List[Dict[str, Any]],
        task: str = "",
        is_completed: bool = False,
        is_paused: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """保存思维链和对话历史

        Args:
            thought_chain: Thought 对象列表（支持原 Thought dataclass 或 dict）
            messages: 对话历史
            task: 任务描述
            is_completed: 是否已完成
            is_paused: 是否暂停
            metadata: 额外元数据

        Returns:
            True 保存成功
        """
        # 转换 Thought 对象为 ThoughtSnapshot
        snapshots: List[ThoughtSnapshot] = []
        for thought in thought_chain:
            if isinstance(thought, ThoughtSnapshot):
                snapshots.append(thought)
            elif isinstance(thought, dict):
                snapshots.append(ThoughtSnapshot.from_dict(thought))
            else:
                # 假设是原 Thought dataclass
                snapshots.append(ThoughtSnapshot(
                    step=getattr(thought, "step", len(snapshots)),
                    thought=getattr(thought, "thought", ""),
                    action_type=getattr(thought, "action_type", ""),
                    tool_name=getattr(thought, "tool_name", None),
                    args=getattr(thought, "args", {}),
                    result=getattr(thought, "result", None),
                    reflection=getattr(thought, "reflection", None),
                    success=getattr(thought, "success", True),
                    timestamp=getattr(thought, "timestamp", time.time()),
                ))

        # 创建或更新会话
        if self._session is None:
            self._session = AgentSession(
                session_id=self.session_id,
                task=task,
            )
        self._session.thought_chain = snapshots
        self._session.messages = messages
        self._session.task = task or self._session.task
        self._session.is_completed = is_completed
        self._session.is_paused = is_paused
        self._session.updated_at = time.time()
        if metadata:
            self._session.metadata.update(metadata)

        # 写入磁盘
        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(self._session.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load_chain(self) -> Optional[AgentSession]:
        """加载会话状态

        Returns:
            AgentSession 对象，文件不存在返回 None
        """
        if not self.session_file.exists():
            return None

        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._session = AgentSession.from_dict(data)
            return self._session
        except (json.JSONDecodeError, OSError):
            return None

    def append_thought(
        self,
        thought: Any,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """追加单个思维节点（增量保存）

        Args:
            thought: Thought 对象
            messages: 可选的更新消息列表

        Returns:
            True 保存成功
        """
        if self._session is None:
            self.load_chain()
        if self._session is None:
            self._session = AgentSession(session_id=self.session_id)

        # 转换并追加
        if isinstance(thought, ThoughtSnapshot):
            snapshot = thought
        elif isinstance(thought, dict):
            snapshot = ThoughtSnapshot.from_dict(thought)
        else:
            snapshot = ThoughtSnapshot(
                step=getattr(thought, "step", len(self._session.thought_chain)),
                thought=getattr(thought, "thought", ""),
                action_type=getattr(thought, "action_type", ""),
                tool_name=getattr(thought, "tool_name", None),
                args=getattr(thought, "args", {}),
                result=getattr(thought, "result", None),
                reflection=getattr(thought, "reflection", None),
                success=getattr(thought, "success", True),
                timestamp=getattr(thought, "timestamp", time.time()),
            )

        self._session.thought_chain.append(snapshot)
        if messages is not None:
            self._session.messages = messages
        self._session.updated_at = time.time()

        # 写入磁盘
        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(self._session.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def mark_completed(self, final_answer: str = "") -> bool:
        """标记会话为已完成"""
        if self._session is None:
            return False
        self._session.is_completed = True
        self._session.is_paused = False
        self._session.metadata["final_answer"] = final_answer
        self._session.updated_at = time.time()
        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(self._session.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def mark_paused(self) -> bool:
        """标记会话为已暂停（可用于断点续跑）"""
        if self._session is None:
            return False
        self._session.is_paused = True
        self._session.updated_at = time.time()
        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(self._session.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def delete(self) -> bool:
        """删除会话文件"""
        try:
            if self.session_file.exists():
                self.session_file.unlink()
            self._session = None
            return True
        except Exception:
            return False

    def get_resume_point(self) -> Optional[Dict[str, Any]]:
        """获取续跑点信息

        Returns:
            {
                "session_id": str,
                "task": str,
                "completed_steps": int,
                "last_thought": dict,
                "messages": list,
                "is_paused": bool,
            }
            无可续跑的会话返回 None
        """
        session = self.load_chain()
        if session is None:
            return None
        if session.is_completed:
            return None  # 已完成的会话无需续跑
        if not session.thought_chain:
            return None

        return {
            "session_id": session.session_id,
            "task": session.task,
            "completed_steps": len(session.thought_chain),
            "last_thought": session.thought_chain[-1].to_dict(),
            "messages": session.messages,
            "is_paused": session.is_paused,
        }


# ============================================================================
# 会话列表查询
# ============================================================================

def list_sessions(storage_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """列出所有已保存的会话

    Args:
        storage_dir: 存储目录（None 使用默认）

    Returns:
        会话摘要列表（按更新时间倒序）
    """
    storage = storage_dir or (Path.home() / ".zeroai" / "agent_sessions")
    if not storage.exists():
        return []

    sessions = []
    for f in storage.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            sessions.append({
                "session_id": data.get("session_id", f.stem),
                "task": data.get("task", ""),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "steps": len(data.get("thought_chain", [])),
                "is_completed": data.get("is_completed", False),
                "is_paused": data.get("is_paused", False),
            })
        except Exception:
            continue

    # 按更新时间倒序
    sessions.sort(key=lambda s: s.get("updated_at", 0), reverse=True)
    return sessions


def get_session_by_task(
    task_keyword: str,
    storage_dir: Optional[Path] = None,
) -> Optional[str]:
    """按任务关键词查找会话

    Args:
        task_keyword: 任务关键词
        storage_dir: 存储目录

    Returns:
        匹配的 session_id，未找到返回 None
    """
    sessions = list_sessions(storage_dir)
    for s in sessions:
        if task_keyword.lower() in s.get("task", "").lower():
            return s["session_id"]
    return None


# ============================================================================
# 清理过期会话
# ============================================================================

def cleanup_old_sessions(
    max_age_days: int = 30,
    storage_dir: Optional[Path] = None,
) -> int:
    """清理过期的会话文件

    Args:
        max_age_days: 最大保留天数
        storage_dir: 存储目录

    Returns:
        清理的文件数
    """
    storage = storage_dir or (Path.home() / ".zeroai" / "agent_sessions")
    if not storage.exists():
        return 0

    cutoff = time.time() - max_age_days * 86400
    count = 0
    for f in storage.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                count += 1
        except Exception:
            continue
    return count


__all__ = [
    "ThoughtSnapshot",
    "AgentSession",
    "AgentPersistence",
    "list_sessions",
    "get_session_by_task",
    "cleanup_old_sessions",
]
