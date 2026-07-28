"""专家路由与 OpenRouter 熔断器

迁移来源：tui_agent.py 行 1002-1155

提供：
- route_expert：关键词快速预判（GLM 语义路由的降级方案）
- LRUCache / _expert_route_cache：GLM 语义路由结果缓存
- route_expert_glm：基于 GLM 的语义路由（异步）
- get_expert_config：获取专家对应的模型配置
- OpenRouter 熔断器：
  * _is_openrouter_expert：判断专家是否依赖 OpenRouter
  * _check_openrouter_circuit_breaker：检查是否已熔断
  * _record_openrouter_failure / _record_openrouter_success：记录调用结果

依赖关系：
- constants.py：EXPERT_TEAM, MODEL_CONFIGS
- secrets.py：_make_openai_client
- runtime.py：_interruptible_await
"""
import re
from collections import OrderedDict

from .constants import EXPERT_TEAM, MODEL_CONFIGS
from .secrets import _make_openai_client
from .runtime import _interruptible_await


def route_expert(user_input: str) -> str:
    """关键词快速预判（作为GLM语义判断的降级方案）"""
    text = user_input.lower()
    for expert_key in ("vision", "coder", "security", "devops", "data", "reasoner", "academic", "chinese", "pm"):
        for kw in EXPERT_TEAM[expert_key]["keywords"]:
            kw_lower = kw.lower()
            if kw_lower in text:
                if kw_lower.isascii() and kw_lower.isalpha():
                    if re.search(r'\b' + re.escape(kw_lower) + r'\b', text):
                        return expert_key
                else:
                    return expert_key
    return "knowledge"


# GLM语义路由的缓存（避免重复判断）- 使用 LRU 防止内存泄漏
class LRUCache:
    """线程安全的 LRU 缓存"""
    def __init__(self, maxsize=256):
        self.cache = OrderedDict()
        self.maxsize = maxsize

    def get(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def set(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)

    def __contains__(self, key):
        return key in self.cache

    def __len__(self):
        return len(self.cache)


_expert_route_cache = LRUCache(maxsize=256)


async def route_expert_glm(user_input: str) -> str:
    """用GLM语义判断用户意图，路由到最合适的专家"""
    # 短消息用关键词快速预判（省时间）
    if len(user_input) < 10:
        return route_expert(user_input)

    # 缓存命中
    cache_key = user_input[:200]
    cached = _expert_route_cache.get(cache_key)
    if cached is not None:
        return cached

    glm_cfg = MODEL_CONFIGS["glm-v"]  # 用多模态模型做路由（支持图片消息）
    try:
        client = _make_openai_client("glm-v")
        prompt = f"""判断以下用户问题属于哪个专家领域，只回复一个词：
- coder：编程开发、代码、函数、bug、技术实现
- reasoner：数学推理、逻辑证明、算法分析、复杂计算
- academic：学术论文、公式推导、文献综述、研究方法、LaTeX、定理证明
- chinese：中文写作、文章、报告、文案、邮件
- vision：图片理解、截图分析、视觉
- pm：任务分析、计划制定、翻译、通用问答、解释说明
- knowledge：百科知识、事实查询、翻译、其他

用户问题：{user_input[:300]}

只回复上面列出的一个词，不要回复其他任何内容。"""

        resp = await _interruptible_await(client.chat.completions.create(
            model=glm_cfg["model"],
            messages=[{"role": "system", "content": "你是 ZeroAI 路由分析器，只负责把用户问题分类到一个专家。严格只输出一个英文标识词，不要做解释。"},
                      {"role": "user", "content": prompt}],
            temperature=0.01,
            max_tokens=10,
            stream=False,
            timeout=15,
        ))
        if resp is None:
            # 被 Ctrl+C 中断
            return "knowledge"
        result = resp.choices[0].message.content.strip().lower()
        # 验证返回值
        valid_keys = {"coder", "reasoner", "academic", "chinese", "vision", "pm", "knowledge"}
        for vk in valid_keys:
            if vk in result:
                _expert_route_cache.set(cache_key, vk)
                return vk
        # 无效返回，降级到关键词
        expert_key = route_expert(user_input)
        _expert_route_cache.set(cache_key, expert_key)
        return expert_key
    except Exception:
        # GLM判断失败，降级到关键词
        expert_key = route_expert(user_input)
        _expert_route_cache.set(cache_key, expert_key)
        return expert_key


def get_expert_config(expert_key: str) -> dict:
    """获取专家对应的模型配置（base_url, api_key, model, model_key）"""
    expert = EXPERT_TEAM[expert_key]
    model_key = expert["model_key"]
    base_cfg = MODEL_CONFIGS[model_key]
    return {
        "base_url": base_cfg["base_url"],
        "api_key": base_cfg["api_key"],
        "model": expert["model"],
        "label": expert["label"],
        "model_key": model_key,  # v1.1.0 新增：供 _make_openai_client 识别
    }


# ====== OpenRouter 熔断器（连续失败自动降级，避免用户卡在"思考中…"） ======
_OPENROUTER_FAIL_COUNTS = {}  # {expert_key: 连续失败次数}
_OPENROUTER_CIRCUIT_THRESHOLD = 3  # 连续失败 3 次即熔断


def _is_openrouter_expert(expert_key: str) -> bool:
    """判断专家是否依赖 OpenRouter（需要熔断保护）"""
    try:
        return EXPERT_TEAM[expert_key].get("model_key") == "openrouter"
    except Exception:
        return False


def _check_openrouter_circuit_breaker(expert_key: str) -> bool:
    """检查专家是否已熔断（返回 True 表示应跳过该专家直接降级）"""
    if not _is_openrouter_expert(expert_key):
        return False
    return _OPENROUTER_FAIL_COUNTS.get(expert_key, 0) >= _OPENROUTER_CIRCUIT_THRESHOLD


def _record_openrouter_failure(expert_key: str) -> int:
    """记录一次 OpenRouter 专家失败，返回当前连续失败次数"""
    if not _is_openrouter_expert(expert_key):
        return 0
    cnt = _OPENROUTER_FAIL_COUNTS.get(expert_key, 0) + 1
    _OPENROUTER_FAIL_COUNTS[expert_key] = cnt
    return cnt


def _record_openrouter_success(expert_key: str) -> None:
    """记录一次成功，重置连续失败计数"""
    if _is_openrouter_expert(expert_key):
        _OPENROUTER_FAIL_COUNTS[expert_key] = 0
