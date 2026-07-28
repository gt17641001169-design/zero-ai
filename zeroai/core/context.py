"""Context management for ZeroAI

提供两层上下文管理策略（从 tui_agent.py 迁移并模块化）：

1. cleanup_context（轻量清理，30% 阈值）
   - 纯规则，零延迟
   - 保留用户意图，摘要化工具输出
   - 截断过长的助手消息

2. compress_context（GLM 深度压缩，70% 阈值）
   - 调用 GLM 总结历史对话
   - 保留 system + 最近 N 轮
   - 处理超大上下文

与 tui_agent.py 的兼容性：
    - 保持函数签名一致（messages, context_limit, keep_recent_turns）
    - 返回格式一致（messages list 或 (messages, info) 元组）
    - 可被 tui_agent.py 直接调用（迁移期兼容）
"""
import re
from typing import List, Dict, Any, Optional, Tuple
from collections import deque


# ============================================================================
# 常量（与 tui_agent.py 保持一致）
# ============================================================================

CHARS_PER_TOKEN = 3  # 粗略估算：英文 ~4 字符/token，中文 ~1.5 字符/token，综合取 3

# 主动清理阈值（context_limit 的 30%）
CLEANUP_THRESHOLD_RATIO = 0.3
CLEANUP_KEEP_RECENT_TURNS = 4

# GLM 压缩阈值（context_limit 的 70%）
COMPRESS_THRESHOLD_RATIO = 0.7
KEEP_RECENT_TURNS = 4

# 工具输出摘要最大长度
TOOL_OUTPUT_SUMMARY_MAX_LEN = 300

# 各模型的上下文 token 上限（含 max_new_tokens 余量）
_MODEL_CONTEXT_LIMITS = {
    "glm-4v-flash": 14000,
    "glm-4v": 14000,
    "glm-4.7-flash": 120000,
    "glm-4": 120000,
}


# ============================================================================
# Token 估算
# ============================================================================

def estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """粗略估算消息列表的 token 数

    与 tui_agent.py 的 _estimate_tokens 完全一致，保证迁移期行为一致。
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            # 多模态消息：只统计文本部分
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total_chars += len(part.get("text", ""))
        # 每条消息固定开销（role 等元数据）
        total_chars += 10
    return max(1, total_chars // CHARS_PER_TOKEN)


def get_model_context_limit(model_name: str) -> int:
    """获取模型的安全上下文 token 上限，未知模型返回 0（不截断）"""
    if not model_name:
        return 0
    if model_name in _MODEL_CONTEXT_LIMITS:
        return _MODEL_CONTEXT_LIMITS[model_name]
    model_lower = model_name.lower()
    for kw, limit in _MODEL_CONTEXT_LIMITS.items():
        if kw in model_lower:
            return limit
    return 0


# ============================================================================
# 第1层：主动清理（纯规则，零延迟）
# ============================================================================

def _summarize_tool_output(tool_name: str, content: str) -> str:
    """将冗长的工具输出摘要为简短结论（不调用 AI，纯规则提取）。

    策略：
    1. 如果内容已很短（< TOOL_OUTPUT_SUMMARY_MAX_LEN），原样保留
    2. 否则提取关键信息：工具名 + 内容长度 + 首尾片段 + 关键指标
    """
    if not content:
        return ""
    if not isinstance(content, str):
        content = str(content)

    if len(content) <= TOOL_OUTPUT_SUMMARY_MAX_LEN:
        return content

    # 提取关键指标：百分比、状态词、数字
    indicators = []

    pcts = re.findall(r"(\d+)%", content)
    if pcts:
        indicators.append(f"百分比:{','.join(pcts[:5])}")

    for keyword in ["✅", "⚠️", "🚨", "正常", "警告", "危急", "Error", "错误", "失败"]:
        if keyword in content:
            count = content.count(keyword)
            indicators.append(f"{keyword}×{count}")

    ports = re.findall(r"端口\s*(\d+)", content)
    if ports:
        indicators.append(f"端口:{','.join(ports[:5])}")

    pids = re.findall(r"PID[:\s]+(\d+)", content)
    if pids:
        indicators.append(f"PID:{','.join(pids[:5])}")

    indicator_str = " ".join(indicators) if indicators else "无关键指标"
    head = content[:60].replace("\n", " ").strip()
    tail = content[-60:].replace("\n", " ").strip()

    summary = f"[工具结果已清理 | {tool_name} | 原长度{len(content)}字 | {indicator_str}]\n开头: {head}...\n结尾: ...{tail}"
    return summary


def cleanup_context(
    messages: list,
    context_limit: int,
    keep_recent_turns: int = CLEANUP_KEEP_RECENT_TURNS,
) -> Tuple[list, Dict[str, Any]]:
    """主动清理上下文：保留用户意图和工具结论，丢弃工具原始输出。

    与 compress_context 的区别：
    - compress_context：调用 GLM 总结历史，开销大，阈值高（70%）
    - cleanup_context：纯规则清理，零延迟，阈值低（30%），更早触发

    策略：
    1. 估算 token 数，未超清理阈值则原样返回
    2. 超阈值则：
       - 保留所有 system 消息
       - 保留最近 N 轮完整对话（含工具调用细节）
       - 对较早的消息：
         * user 消息：完整保留（用户意图是核心）
         * assistant 消息含 tool_calls：保留文本内容，移除 tool_calls 字段
         * tool 消息：替换为简短摘要
         * 纯文本 assistant 消息：保留前 300 字

    Returns:
        (cleaned_messages, cleanup_info)
    """
    est_tokens = estimate_tokens(messages)
    threshold = int(context_limit * CLEANUP_THRESHOLD_RATIO)

    if est_tokens <= threshold:
        return messages, {"triggered": False, "reason": "未超清理阈值"}

    # 分离 system 消息和对话消息
    system_msgs = []
    convo_msgs = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msgs.append(msg)
        else:
            convo_msgs.append(msg)

    # 找到最近 N 轮的起始位置
    keep_start_idx = 0
    user_count = 0
    for i in range(len(convo_msgs) - 1, -1, -1):
        if convo_msgs[i].get("role") == "user":
            user_count += 1
            if user_count >= keep_recent_turns:
                keep_start_idx = i
                break

    to_clean = convo_msgs[:keep_start_idx]
    keep_recent = convo_msgs[keep_start_idx:]

    if len(to_clean) < 2:
        return messages, {"triggered": False, "reason": "待清理消息过少"}

    # 对待清理部分进行摘要化
    cleaned_msgs = []
    tool_cleaned_count = 0
    assistant_cleaned_count = 0
    tokens_saved = 0

    for msg in to_clean:
        role = msg.get("role")
        content = msg.get("content", "")
        old_tokens = estimate_tokens([msg])

        if role == "user":
            cleaned_msgs.append(msg)
        elif role == "tool":
            tool_name = msg.get("name", "unknown_tool")
            content_str = content if isinstance(content, str) else str(content)
            summarized = _summarize_tool_output(tool_name, content_str)
            new_msg = {
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "name": tool_name,
                "content": summarized,
            }
            cleaned_msgs.append(new_msg)
            tool_cleaned_count += 1
        elif role == "assistant":
            new_msg = {"role": "assistant", "content": content}
            if isinstance(content, str) and len(content) > 300:
                new_msg["content"] = content[:300] + "...[已截断]"
                assistant_cleaned_count += 1
            cleaned_msgs.append(new_msg)
        else:
            cleaned_msgs.append(msg)

        new_tokens = estimate_tokens([cleaned_msgs[-1]])
        tokens_saved += max(0, old_tokens - new_tokens)

    new_messages = system_msgs + cleaned_msgs + keep_recent
    new_tokens_total = estimate_tokens(new_messages)

    return new_messages, {
        "triggered": True,
        "old_tokens": est_tokens,
        "new_tokens": new_tokens_total,
        "tokens_saved": tokens_saved,
        "tool_cleaned": tool_cleaned_count,
        "assistant_cleaned": assistant_cleaned_count,
        "old_count": len(messages),
        "new_count": len(new_messages),
    }


# ============================================================================
# 第2层：GLM 深度压缩
# ============================================================================

def _split_messages_for_compress(
    messages: list,
    keep_recent_turns: int = KEEP_RECENT_TURNS,
) -> Tuple[list, list, list]:
    """将消息拆分为：system部分、待压缩部分、保留的近期部分

    返回：(system_msgs, to_compress_msgs, keep_msgs)
    """
    system_msgs = []
    convo_msgs = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msgs.append(msg)
        else:
            convo_msgs.append(msg)

    keep_start_idx = 0
    user_count = 0
    for i in range(len(convo_msgs) - 1, -1, -1):
        if convo_msgs[i].get("role") == "user":
            user_count += 1
            if user_count >= keep_recent_turns:
                keep_start_idx = i
                break

    to_compress = convo_msgs[:keep_start_idx]
    keep_recent = convo_msgs[keep_start_idx:]
    return system_msgs, to_compress, keep_recent


async def compress_context(
    messages: list,
    context_limit: int,
    keep_recent_turns: int = KEEP_RECENT_TURNS,
) -> list:
    """压缩对话上下文（调用 GLM 总结）

    策略：
    1. 估算当前 token 数，未超阈值则原样返回
    2. 超阈值则：保留 system + 最近 N 轮，中间历史用 GLM 总结

    注意：此函数为 async，调用方需 await。
    """
    est_tokens = estimate_tokens(messages)
    threshold = int(context_limit * COMPRESS_THRESHOLD_RATIO)

    if est_tokens <= threshold:
        return messages

    system_msgs, to_compress, keep_recent = _split_messages_for_compress(messages, keep_recent_turns)

    if len(to_compress) < 4:
        return messages

    # 构造 GLM 总结输入
    summary_input = "请将以下对话历史压缩为简洁的摘要，保留关键信息（用户需求、已完成的操作、重要结论），不超过500字：\n\n"
    for msg in to_compress:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        elif not isinstance(content, str):
            content = str(content)
        summary_input += f"【{role}】{content[:500]}\n\n"

    # 调用 GLM 总结
    try:
        from .llm import LLMClient
        llm = LLMClient("glm")
        summary = await llm.chat(
            system_prompt="你是 ZeroAI 的对话压缩器，把冗长历史压缩为简洁摘要，保留用户需求、已完成操作、重要结论，不超过500字。",
            user_prompt=summary_input,
            temperature=0.1,
            max_tokens=600,
            stream=False,
            timeout=30,
        )
        summary = (summary or "").strip()
    except Exception:
        # 压缩失败，降级为简单截断
        summary = "【历史对话摘要（压缩失败，已截断）】\n"
        for msg in to_compress[-6:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            elif not isinstance(content, str):
                content = str(content)
            summary += f"【{role}】{content[:200]}\n"

    compressed_msg = {
        "role": "system",
        "content": f"【对话历史摘要】以下是之前对话的压缩摘要，请基于此继续对话：\n\n{summary}",
    }

    return system_msgs + [compressed_msg] + keep_recent


async def cleanup_and_compress(
    messages: list,
    context_limit: int,
    log_func=None,
) -> list:
    """统一上下文管理：先轻量清理，再按需压缩。

    两层防护：
    1. cleanup_context（30% 阈值）：纯规则，零延迟，摘要化早期工具输出
    2. compress_context（70% 阈值）：调用 GLM 总结，处理超大上下文

    在调用 AI 前调用此函数，自动决定是否需要清理/压缩。

    Args:
        messages: 消息列表
        context_limit: 上下文 token 上限
        log_func: 可选的日志输出函数（用于 TUI 显示清理进度）

    Returns:
        处理后的消息列表
    """
    try:
        est_tokens = estimate_tokens(messages)

        # 第1层：主动清理（30% 阈值）
        cleanup_threshold = int(context_limit * CLEANUP_THRESHOLD_RATIO)
        if est_tokens > cleanup_threshold and len(messages) > 8:
            old_tokens = est_tokens
            old_count = len(messages)
            messages, info = cleanup_context(messages, context_limit)

            if info.get("triggered"):
                new_tokens = info["new_tokens"]
                if log_func:
                    log_func(
                        f"上下文主动清理：工具输出摘要化 {info['tool_cleaned']} 个，"
                        f"助手消息截断 {info['assistant_cleaned']} 个；"
                        f"{old_count}→{info['new_count']} 条消息，"
                        f"约 {old_tokens}→{new_tokens} tokens（节省 {old_tokens - new_tokens}）"
                    )
                est_tokens = new_tokens

        # 第2层：GLM 压缩（70% 阈值，清理后仍超限才触发）
        compress_threshold = int(context_limit * COMPRESS_THRESHOLD_RATIO)
        if est_tokens > compress_threshold and len(messages) > 10:
            if log_func:
                log_func(
                    f"上下文深度压缩：清理后仍超阈值（{est_tokens} > {compress_threshold}），调用 GLM 总结…"
                )
            old_count = len(messages)
            old_tokens = est_tokens
            messages = await compress_context(messages, context_limit)
            new_tokens = estimate_tokens(messages)
            new_count = len(messages)
            if log_func:
                log_func(
                    f"压缩完成：{old_count}→{new_count} 条消息，"
                    f"约 {old_tokens}→{new_tokens} tokens"
                )
    except Exception as e:
        if log_func:
            log_func(f"上下文管理跳过：{str(e)[:80]}")

    return messages


# ============================================================================
# ContextManager 类（兼容原有接口）
# ============================================================================

class ContextManager:
    """Manage conversation context with compression and cleanup

    保留原有类接口，兼容 zeroai/core/__init__.py 的导入。
    新代码建议直接使用 cleanup_and_compress() 函数。
    """

    def __init__(self, max_tokens: int = 8000, keep_recent_turns: int = 4):
        """Initialize context manager"""
        self.max_tokens = max_tokens
        self.keep_recent_turns = keep_recent_turns
        self.messages: List[Dict[str, Any]] = []
        self._chars_per_token = CHARS_PER_TOKEN

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from text"""
        return len(text) // self._chars_per_token

    def add_message(self, role: str, content: str):
        """Add a message to context"""
        self.messages.append({
            "role": role,
            "content": content
        })

    def get_context_tokens(self) -> int:
        """Get total token count of current context"""
        return estimate_tokens(self.messages)

    def compress_if_needed(self) -> bool:
        """Compress context if it exceeds max tokens（同步版本，仅做清理）"""
        if self.get_context_tokens() <= self.max_tokens:
            return False

        # 同步路径：只做清理（不调用 GLM）
        self.messages, info = cleanup_context(self.messages, self.max_tokens)
        return info.get("triggered", False)

    async def compress_by_glm(self) -> bool:
        """GLM 深度压缩（异步，调用 GLM 总结）"""
        est_tokens = self.get_context_tokens()
        threshold = int(self.max_tokens * COMPRESS_THRESHOLD_RATIO)

        if est_tokens <= threshold:
            return False

        self.messages = await compress_context(self.messages, self.max_tokens)
        return True

    async def cleanup_and_compress(self, log_func=None):
        """统一上下文管理（异步，两层防护）"""
        self.messages = await cleanup_and_compress(
            self.messages, self.max_tokens, log_func
        )

    def _summarize_messages(self, messages: List[Dict[str, Any]]) -> str:
        """Summarize older messages（兼容旧接口）"""
        summary_parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                summary_parts.append(f"{role}: {content[:100]}...")
        return "\n".join(summary_parts[-10:])

    def cleanup_tool_outputs(self):
        """Clean up tool outputs to reduce context size"""
        cleaned = []
        for msg in self.messages:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if len(content) > 200:
                    msg = msg.copy()
                    msg["content"] = content[:200] + "... [已截断]"
            cleaned.append(msg)
        self.messages = cleaned

    def clear(self):
        """Clear all messages"""
        self.messages = []

    def get_messages(self) -> List[Dict[str, Any]]:
        """Get current messages"""
        return self.messages.copy()

    def set_messages(self, messages: List[Dict[str, Any]]):
        """Set messages"""
        self.messages = messages.copy()

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: str):
        """Add tool result to context"""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })

    def add_assistant_message(self, content: str, tool_calls: Optional[List[Dict]] = None):
        """Add assistant message with optional tool calls"""
        msg = {
            "role": "assistant",
            "content": content
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def get_last_user_message(self) -> Optional[str]:
        """Get the last user message"""
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return msg.get("content")
        return None

    def remove_last_message(self):
        """Remove the last message"""
        if self.messages:
            self.messages.pop()


# ============================================================================
# 全局实例管理
# ============================================================================

_context_manager: Optional[ContextManager] = None


def get_context_manager() -> ContextManager:
    """Get global context manager instance"""
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager


def create_context_manager(max_tokens: int = 8000, keep_recent_turns: int = 4) -> ContextManager:
    """Create a new context manager"""
    return ContextManager(max_tokens=max_tokens, keep_recent_turns=keep_recent_turns)
