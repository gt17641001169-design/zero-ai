"""响应文本处理工具

迁移来源：tui_agent.py 行 4975-5084, 9989-10022

提供以下纯函数：
- _strip_model_tokens：过滤模型内部特殊标签（如 <|xxx|>）
- _parse_think_tags：解析 <think>...</think> 思考链标签
- _jaccard_similarity：基于 n-gram 的 Jaccard 相似度（用于专家回答去重）
- _truncate_expert_response：截断专家回答到指定字符数
- _sanitize_identity_leak：检测并过滤身份泄露内容（API 响应层防线）

本模块无外部依赖，仅使用标准库 re。
"""
import re


# ====== 身份泄露过滤（API 响应层拦截，作为 SYSTEM_PROMPT 规则的后置防线） ======
# 检测模型输出中的自报家门内容，替换为标准 ZeroAI 身份回答
_IDENTITY_LEAK_PATTERNS = [
    # "我是智谱/GLM/GPT/Claude/Gemini..." 自报家门
    re.compile(r"我是.{0,15}(智谱|GLM[-\s]?130|ChatGLM|GPT[-\s]?[0-9]|Claude|Gemini|PaLM|LLaMA|Qwen)", re.IGNORECASE),
    # "基于 XX 模型微调/训练/推出"
    re.compile(r"基于.{0,20}(GLM|GPT|Claude|Gemini|LLaMA|Qwen).{0,10}(微调|训练|推出)", re.IGNORECASE),
    # "由 XX 公司推出/发布/开发/创建"
    re.compile(r"由.{0,15}(智谱|OpenAI|Anthropic|Google|Meta|Microsoft).{0,10}(推出|发布|开发|创建)", re.IGNORECASE),
    # 直接出现底层模型标识
    re.compile(r"(智谱\s*AI|GLM[-\s]?130B|ChatGLM|我是\s*GLM|我的模型是\s*GLM)", re.IGNORECASE),
    # "130B 参数规模" 等参数泄露
    re.compile(r"130\s*B\s*参数"),
]
_IDENTITY_REPLACEMENT = "我是 ZeroAI，一个终端 AI 编程助手。"


def _strip_model_tokens(text: str) -> str:
    """过滤模型内部特殊标签（如 <|xxx|> 等）

    这些标签是推理模型（如 GLM-4V）的思维链标记，不应显示给用户。
    支持流式累积后的完整过滤（跨 chunk 拼接后标签完整即可被清除）。

    过滤的标签模式：<|xxx|> 和 <|/xxx|>（xxx 不含 | 字符）
    """
    if not text:
        return text
    # 删除所有 <|...|> 格式的标签（开标签、闭标签、自闭合标签）
    return re.sub(r'<\|[^|]*\|>', '', text)


def _parse_think_tags(content: str) -> tuple:
    """从累积 content：think_content = 标签间内容, body_content = </think>之后内容
    - 多个 <think> 块：合并所有 think 内容，body 为剩余内容
    """
    if not content:
        return "", ""
    think_content_parts = []
    body_parts = []
    pos = 0
    while pos < len(content):
        # 查找下一个 <think>
        start = content.find("<think>", pos)
        if start == -1:
            # 没有更多 <think>，剩余全部为正文
            body_parts.append(content[pos:])
            break
        # <think> 之前的内容归入正文
        if start > pos:
            body_parts.append(content[pos:start])
        # 查找对应的 </think>
        end = content.find("</think>", start + len("<think>"))
        if end == -1:
            # <think> 未闭合，剩余内容均为思考
            think_text = content[start + len("<think>"):]
            if think_text:
                think_content_parts.append(think_text)
            pos = len(content)
            break
        # 完整 <think>...</think>
        think_text = content[start + len("<think>"):end]
        if think_text:
            think_content_parts.append(think_text)
        pos = end + len("</think>")
    think_content = "\n".join(p.strip() for p in think_content_parts if p.strip())
    body_content = "".join(body_parts)
    # 去除正文开头的换行
    while body_content.startswith("\n"):
        body_content = body_content[1:]
    return think_content, body_content


def _jaccard_similarity(s1: str, s2: str) -> float:
    """计算两段文本的 Jaccard 相似度（基于字符 n-gram 集合）

    用于专家回答去重：相似度越高说明回答越重复。
    返回 0.0-1.0 的浮点数。
    """
    if not s1 or not s2:
        return 0.0
    # 使用 3-gram（兼顾中英文，对短文本也有效）
    n = 3
    if len(s1) < n or len(s2) < n:
        # 文本过短时直接用字符集合
        set1, set2 = set(s1), set(s2)
    else:
        set1 = {s1[i:i + n] for i in range(len(s1) - n + 1)}
        set2 = {s2[i:i + n] for i in range(len(s2) - n + 1)}
    if not set1 or not set2:
        return 0.0
    inter = len(set1 & set2)
    union = len(set1 | set2)
    return inter / union if union else 0.0


def _truncate_expert_response(text: str, max_chars: int) -> str:
    """截断专家回答到指定字符数，并附加截断提示

    用于 HYBRID_EXPERT_MAX_CHARS 限制：避免单个专家回答过长导致汇总 token 暴涨。
    """
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text
    # 在 max_chars 附近找换行或句号，避免截断在词中间
    cut = text[:max_chars]
    # 优先在最近的换行处截断
    nl = cut.rfind("\n")
    if nl > max_chars * 0.7:
        cut = cut[:nl]
    else:
        # 退而求其次在句号/问号处截断
        for sep in ("。", "？", "！", ".", "?", "!"):
            sp = cut.rfind(sep)
            if sp > max_chars * 0.7:
                cut = cut[:sp + 1]
                break
    return cut + "\n\n…（专家回答已截断，仅汇总关键部分）"


def _sanitize_identity_leak(text: str) -> tuple:
    """检测并过滤身份泄露内容

    Returns:
        (sanitized_text, leaked: bool)  leaked 为 True 表示检测到并已过滤
    """
    if not text:
        return text, False
    leaked = False
    result = text
    for pattern in _IDENTITY_LEAK_PATTERNS:
        if pattern.search(result):
            leaked = True
            result = pattern.sub(_IDENTITY_REPLACEMENT, result)
    return result, leaked
