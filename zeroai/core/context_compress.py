"""上下文清理与压缩

迁移来源：tui_agent.py 行 1173-1643

提供两层上下文管理：
1. cleanup_context（30% 阈值）：纯规则清理，零延迟，摘要化早期工具输出
2. compress_context（70% 阈值）：调用 GLM 总结，处理超大上下文

辅助函数：
- _summarize_tool_output：纯规则提取工具输出关键信息
- _estimate_tokens：粗略估算消息列表 token 数
- _get_model_context_limit / _truncate_messages_for_context：按模型上限截断
- _model_supports_vision / _filter_messages_for_model：多模态消息过滤
- _split_messages_for_compress：拆分消息用于压缩

依赖关系：
- constants.py：CHARS_PER_TOKEN, CLEANUP_THRESHOLD_RATIO, COMPRESS_THRESHOLD_RATIO,
  CLEANUP_KEEP_RECENT_TURNS, KEEP_RECENT_TURNS, TOOL_OUTPUT_SUMMARY_MAX_LEN,
  _VISION_MODEL_KEYWORDS, _MODEL_CONTEXT_LIMITS, MODEL_CONFIGS
- secrets.py：_make_openai_client

注意：cleanup_and_compress 中的 log_func 回调用于 TUI 显示进度。
原 tui_agent.py 使用 _load_svg_icon('tool'/'check'/'warning') 和 C_DIM 颜色常量，
这些属于 TUI 表现层。本模块提供回退实现（空字符串图标 + 灰色常量），
TUI 层可通过传入的 log_func 自行处理图标/颜色的最终渲染。
"""
import re

from .constants import (
    CHARS_PER_TOKEN,
    CLEANUP_THRESHOLD_RATIO,
    COMPRESS_THRESHOLD_RATIO,
    CLEANUP_KEEP_RECENT_TURNS,
    KEEP_RECENT_TURNS,
    TOOL_OUTPUT_SUMMARY_MAX_LEN,
    _VISION_MODEL_KEYWORDS,
    _MODEL_CONTEXT_LIMITS,
    MODEL_CONFIGS,
)
from .secrets import _make_openai_client


# ====== TUI 表现层回退常量 ======
# 原 tui_agent.py 中 _load_svg_icon 返回 SVG 图标字符串，C_DIM 为灰色 hex
# 核心层不依赖 TUI，提供回退：图标用空字符串，颜色用灰色 hex
# TUI 层若需完整图标，可在传入的 log_func 中自行替换
_C_DIM_FALLBACK = "#6B6B75"  # 灰色（次要文字/说明），与 tui_agent.py 的 C_DIM 一致


def _load_svg_icon_fallback(name: str) -> str:
    """TUI 图标回退实现：返回空字符串（核心层不依赖 SVG 资源）

    TUI 层可在外部包装 log_func 以注入真实图标。
    """
    return ""


def _summarize_tool_output(tool_name: str, content: str) -> str:
    """将冗长的工具输出摘要为简短结论（不调用 AI，纯规则提取）。

    策略：
    1. 如果内容已很短（< TOOL_OUTPUT_SUMMARY_MAX_LEN），原样保留
    2. 否则提取关键信息：工具名 + 内容长度 + 首尾片段 + 关键指标
    """
    if not content or not isinstance(content, str):
        return content if content else ""

    # 非 str 类型转 str
    if not isinstance(content, str):
        content = str(content)

    # 很短的工具输出直接保留
    if len(content) <= TOOL_OUTPUT_SUMMARY_MAX_LEN:
        return content

    # 提取关键指标：百分比、状态词、数字
    indicators = []

    # 磁盘/内存/CPU 百分比
    pcts = re.findall(r"(\d+)%", content)
    if pcts:
        indicators.append(f"百分比:{','.join(pcts[:5])}")

    # 状态标记
    for keyword in ["✅", "⚠️", "🚨", "正常", "警告", "危急", "Error", "错误", "失败"]:
        if keyword in content:
            count = content.count(keyword)
            indicators.append(f"{keyword}×{count}")

    # 端口号
    ports = re.findall(r"端口\s*(\d+)", content)
    if ports:
        indicators.append(f"端口:{','.join(ports[:5])}")

    # PID
    pids = re.findall(r"PID[:\s]+(\d+)", content)
    if pids:
        indicators.append(f"PID:{','.join(pids[:5])}")

    # 构造摘要
    indicator_str = " ".join(indicators) if indicators else "无关键指标"
    head = content[:60].replace("\n", " ").strip()
    tail = content[-60:].replace("\n", " ").strip()

    summary = f"[工具结果已清理 | {tool_name} | 原长度{len(content)}字 | {indicator_str}]\n开头: {head}...\n结尾: ...{tail}"
    return summary


def cleanup_context(messages: list, context_limit: int,
                    keep_recent_turns: int = CLEANUP_KEEP_RECENT_TURNS) -> tuple:
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
         * 纯文本 assistant 消息：保留前 200 字

    Returns:
        (cleaned_messages, cleanup_info)
        - cleaned_messages: 清理后的消息列表
        - cleanup_info: dict，含清理统计信息
    """
    est_tokens = _estimate_tokens(messages)
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

    # 分为待清理部分和保留部分
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
        old_tokens = _estimate_tokens([msg])

        if role == "user":
            # 用户消息完整保留（用户意图是核心）
            cleaned_msgs.append(msg)
        elif role == "tool":
            # 工具消息：替换为简短摘要
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
            # 助手消息：保留文本，移除 tool_calls（避免 API 报错）
            new_msg = {"role": "assistant", "content": content}
            # 如果内容过长，截断保留前 300 字
            if isinstance(content, str) and len(content) > 300:
                new_msg["content"] = content[:300] + "...[已截断]"
                assistant_cleaned_count += 1
            # 注意：不保留 tool_calls 字段，因为没有对应的 tool 消息会报错
            cleaned_msgs.append(new_msg)
        else:
            # 其他角色原样保留
            cleaned_msgs.append(msg)

        new_tokens = _estimate_tokens([cleaned_msgs[-1]])
        tokens_saved += max(0, old_tokens - new_tokens)

    new_messages = system_msgs + cleaned_msgs + keep_recent
    new_tokens_total = _estimate_tokens(new_messages)

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


async def cleanup_and_compress(app, log_func=None):
    """统一上下文管理：先轻量清理，再按需压缩。

    两层防护：
    1. cleanup_context（30% 阈值）：纯规则，零延迟，摘要化早期工具输出
    2. compress_context（70% 阈值）：调用 GLM 总结，处理超大上下文

    在调用 AI 前调用此函数，自动决定是否需要清理/压缩。

    Args:
        app: ZeroAIApp 实例（需要 self.messages, self.context_limit）
        log_func: 可选的日志输出函数（用于 TUI 显示清理进度）

    注意：log_func 的调用签名与 tui_agent.py 一致（消息文本, 颜色）。
    原 tui_agent.py 使用 _load_svg_icon('tool'/'check'/'warning') 注入 SVG 图标，
    本模块使用回退实现（空字符串），TUI 层可在 log_func 中自行处理图标替换。
    """
    # 延迟导入 TUI 表现层（若可用），否则使用回退
    try:
        from ..tui.icons import _load_svg_icon, C_DIM  # type: ignore
    except Exception:
        _load_svg_icon = _load_svg_icon_fallback
        C_DIM = _C_DIM_FALLBACK

    try:
        est_tokens = _estimate_tokens(app.messages)

        # ── 第1层：主动清理（30% 阈值）──
        cleanup_threshold = int(app.context_limit * CLEANUP_THRESHOLD_RATIO)
        if est_tokens > cleanup_threshold and len(app.messages) > 8:
            old_tokens = est_tokens
            old_count = len(app.messages)
            app.messages, info = cleanup_context(app.messages, app.context_limit)

            if info.get("triggered"):
                new_tokens = info["new_tokens"]
                if log_func:
                    log_func(
                        f"  {_load_svg_icon('tool')} 上下文主动清理\n"
                        f"  │ 工具输出摘要化：{info['tool_cleaned']} 个工具结果，"
                        f"{info['assistant_cleaned']} 个助手消息截断\n"
                        f"  │ {old_count}→{info['new_count']} 条消息，"
                        f"约 {old_tokens}→{new_tokens} tokens（节省 {old_tokens - new_tokens}）\n"
                        f"  └─\n",
                        C_DIM,
                    )
                est_tokens = new_tokens  # 更新当前 token 数，供下层判断

        # ── 第2层：GLM 压缩（70% 阈值，清理后仍超限才触发）──
        compress_threshold = int(app.context_limit * COMPRESS_THRESHOLD_RATIO)
        if est_tokens > compress_threshold and len(app.messages) > 10:
            if log_func:
                log_func(
                    f"  {_load_svg_icon('tool')} 上下文深度压缩\n"
                    f"  │ 清理后仍超阈值（{est_tokens} > {compress_threshold}），调用 GLM 总结…\n",
                    C_DIM,
                )
            old_count = len(app.messages)
            old_tokens = est_tokens
            app.messages = await compress_context(app.messages, app.context_limit)
            new_tokens = _estimate_tokens(app.messages)
            new_count = len(app.messages)
            if log_func:
                log_func(
                    f"  {_load_svg_icon('check')} 压缩完成："
                    f"{old_count}→{new_count} 条消息，"
                    f"约 {old_tokens}→{new_tokens} tokens\n"
                    f"  └─\n",
                    C_DIM,
                )
    except Exception as e:
        if log_func:
            log_func(
                f"  {_load_svg_icon('warning')} 上下文管理跳过：{str(e)[:80]}\n",
                C_DIM,
            )


def _estimate_tokens(messages: list) -> int:
    """粗略估算消息列表的 token 数"""
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


def _get_model_context_limit(model_name: str) -> int:
    """获取模型的安全上下文 token 上限，未知模型返回 0（不截断）"""
    if not model_name:
        return 0
    # 精确匹配
    if model_name in _MODEL_CONTEXT_LIMITS:
        return _MODEL_CONTEXT_LIMITS[model_name]
    # 模糊匹配
    model_lower = model_name.lower()
    for kw, limit in _MODEL_CONTEXT_LIMITS.items():
        if kw in model_lower:
            return limit
    return 0


def _truncate_messages_for_context(messages: list, max_tokens: int) -> list:
    """按 token 上限截断消息列表：保留 system 消息 + 最近的对话

    策略：
    1. 始终保留所有 system 消息
    2. 从最新消息向前保留，直到达到 token 上限
    3. 如果第一条保留的非 system 消息不是 user，则补一条占位 user 消息
    """
    if max_tokens <= 0:
        return messages

    est_tokens = _estimate_tokens(messages)
    if est_tokens <= max_tokens:
        return messages  # 未超限，无需截断

    # 分离 system 消息和对话消息
    system_msgs = []
    convo_msgs = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msgs.append(msg)
        else:
            convo_msgs.append(msg)

    # 计算 system 消息占用的 tokens
    system_tokens = _estimate_tokens(system_msgs)
    available_tokens = max_tokens - system_tokens
    if available_tokens < 1000:
        # system 消息本身就超限了，只保留最新的几条 system
        system_msgs = system_msgs[-1:]
        system_tokens = _estimate_tokens(system_msgs)
        available_tokens = max_tokens - system_tokens

    # 从最新消息向前保留
    keep_convo = []
    used_tokens = 0
    for msg in reversed(convo_msgs):
        msg_tokens = _estimate_tokens([msg])
        if used_tokens + msg_tokens > available_tokens:
            break
        keep_convo.insert(0, msg)
        used_tokens += msg_tokens

    if not keep_convo:
        # 至少保留最后一条消息
        if convo_msgs:
            keep_convo = [convo_msgs[-1]]

    # 确保第一条是 user 消息（部分模型要求）
    if keep_convo and keep_convo[0].get("role") not in ("user",):
        keep_convo.insert(0, {"role": "user", "content": "[ earlier conversation truncated ]"})

    return system_msgs + keep_convo


def _model_supports_vision(model_name: str) -> bool:
    """判断模型是否支持多模态（图片输入）"""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return any(kw in model_lower for kw in _VISION_MODEL_KEYWORDS)


def _filter_messages_for_model(messages: list, model_name: str) -> list:
    """根据模型是否支持多模态，过滤消息中的图片内容，并按模型上下文限制截断

    - 支持多模态的模型：保留图片
    - 不支持多模态的模型：将 content 中的 image_url 部分过滤掉，只保留 text
      如果过滤后 content 为空，则替换为占位文本"[图片已忽略，当前模型不支持图片]"
    - 所有模型：按模型上下文限制自动截断旧消息（保留 system + 最近对话）
    """
    # 第1步：按模型上下文限制截断（防止超 token 报错）
    ctx_limit = _get_model_context_limit(model_name)
    if ctx_limit > 0:
        messages = _truncate_messages_for_context(messages, ctx_limit)

    # 第2步：过滤图片内容
    if _model_supports_vision(model_name):
        return messages

    filtered = []
    for msg in messages:
        msg_copy = dict(msg)
        content = msg_copy.get("content")
        if isinstance(content, list):
            # 多模态 content：过滤 image_url，只保留 text
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part["text"])
                    elif part.get("type") == "image_url":
                        # 图片被过滤，添加占位说明
                        if not any("图片" in t for t in text_parts):
                            text_parts.append("[用户发送了图片，但当前模型不支持图片输入，图片已忽略]")
            msg_copy["content"] = "\n".join(text_parts) if text_parts else "[图片已忽略]"
        filtered.append(msg_copy)
    return filtered


def _split_messages_for_compress(messages: list, keep_recent_turns: int = KEEP_RECENT_TURNS):
    """将消息拆分为：system部分、待压缩部分、保留的近期部分
    返回：(system_msgs, to_compress_msgs, keep_msgs)
    """
    # 分离 system 消息（不压缩）
    system_msgs = []
    convo_msgs = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msgs.append(msg)
        else:
            convo_msgs.append(msg)

    # 保留最近 N 轮（一轮 = user + assistant，可能还有 tool 消息）
    # 从后往前找 keep_recent_turns 个 user 消息的位置
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


async def compress_context(messages: list, context_limit: int, keep_recent_turns: int = KEEP_RECENT_TURNS) -> list:
    """压缩对话上下文
    策略：
    1. 估算当前 token 数，未超阈值则原样返回
    2. 超阈值则：保留 system + 最近 N 轮，中间历史用 GLM 总结
    返回：压缩后的 messages 列表
    """
    est_tokens = _estimate_tokens(messages)
    threshold = int(context_limit * COMPRESS_THRESHOLD_RATIO)

    if est_tokens <= threshold:
        return messages  # 未超阈值，无需压缩

    system_msgs, to_compress, keep_recent = _split_messages_for_compress(messages, keep_recent_turns)

    # 待压缩部分为空或太少，不压缩
    if len(to_compress) < 4:
        return messages

    # 用 GLM 总结待压缩的历史对话
    glm_cfg = MODEL_CONFIGS["glm"]
    summary_input = "请将以下对话历史压缩为简洁的摘要，保留关键信息（用户需求、已完成的操作、重要结论），不超过500字：\n\n"
    for msg in to_compress:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            # 多模态内容只取文本
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        elif not isinstance(content, str):
            content = str(content)
        # 每条消息截断，避免总结输入过长
        summary_input += f"【{role}】{content[:500]}\n\n"

    try:
        client = _make_openai_client("glm")
        resp = await client.chat.completions.create(
            model=glm_cfg["model"],
            messages=[{"role": "system", "content": "你是 ZeroAI 的对话压缩器，把冗长历史压缩为简洁摘要，保留用户需求、已完成操作、重要结论，不超过500字。"},
                      {"role": "user", "content": summary_input}],
            temperature=0.1,
            max_tokens=600,
            stream=False,
            timeout=30,
        )
        summary = resp.choices[0].message.content.strip()
    except Exception:
        # 压缩失败，降级为简单截断（保留每条消息前200字）
        summary = "【历史对话摘要（压缩失败，已截断）】\n"
        for msg in to_compress[-6:]:  # 最近6条
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            elif not isinstance(content, str):
                content = str(content)
            summary += f"【{role}】{content[:200]}\n"

    # 构造压缩后的消息列表
    compressed_msg = {
        "role": "system",
        "content": f"【对话历史摘要】以下是之前对话的压缩摘要，请基于此继续对话：\n\n{summary}",
    }

    new_messages = system_msgs + [compressed_msg] + keep_recent
    return new_messages
