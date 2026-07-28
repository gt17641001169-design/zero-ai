"""Expert routing and management for ZeroAI

提供两层专家路由：

1. ExpertRouter（单专家路由）
   - route_by_keywords：基于关键词匹配
   - route_by_glm：基于 GLM 语义分析
   - LRU 缓存加速

2. HybridExpertSystem（混合模式，多专家协作）
   - select_experts：GLM 分析任务，选择多个专家
   - call_experts_parallel：多专家并行调用
   - call_experts_chain：协作链模式（顺序传递结果）
   - dedup_responses：基于 Jaccard 相似度去重
   - summarize_responses：GLM 汇总多专家回答
   - 专家记忆：每个专家独立上下文，避免主上下文污染

从 tui_agent.py 迁移并模块化，保持核心逻辑一致。
"""
import asyncio
import re
from typing import Dict, List, Optional, Tuple, Any, Callable
from collections import OrderedDict, deque
from .config import get_config
from .llm import LLMClient, MultiModelClient, get_multi_model_client


# ============================================================================
# LRU 缓存
# ============================================================================

class LRUCache:
    """Thread-safe LRU cache for expert routing"""

    def __init__(self, maxsize: int = 256):
        self.cache = OrderedDict()
        self.maxsize = maxsize

    def get(self, key: str) -> Optional[str]:
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def set(self, key: str, value: str):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)

    def __contains__(self, key: str) -> bool:
        return key in self.cache

    def __len__(self) -> int:
        return len(self.cache)


# ============================================================================
# 文本工具（从 tui_agent.py 迁移）
# ============================================================================

def jaccard_similarity(s1: str, s2: str) -> float:
    """计算两段文本的 Jaccard 相似度（基于字符 n-gram 集合）

    用于专家回答去重：相似度越高说明回答越重复。
    返回 0.0-1.0 的浮点数。
    """
    if not s1 or not s2:
        return 0.0
    n = 3
    if len(s1) < n or len(s2) < n:
        set1, set2 = set(s1), set(s2)
    else:
        set1 = {s1[i:i + n] for i in range(len(s1) - n + 1)}
        set2 = {s2[i:i + n] for i in range(len(s2) - n + 1)}
    if not set1 or not set2:
        return 0.0
    inter = len(set1 & set2)
    union = len(set1 | set2)
    return inter / union if union else 0.0


def truncate_expert_response(text: str, max_chars: int) -> str:
    """截断专家回答到指定字符数，并附加截断提示

    用于 HYBRID_EXPERT_MAX_CHARS 限制：避免单个专家回答过长导致汇总 token 暴涨。
    """
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    nl = cut.rfind("\n")
    if nl > max_chars * 0.7:
        cut = cut[:nl]
    else:
        for sep in ("。", "？", "！", ".", "?", "!"):
            sp = cut.rfind(sep)
            if sp > max_chars * 0.7:
                cut = cut[:sp + 1]
                break
    return cut + "\n\n…（专家回答已截断，仅汇总关键部分）"


# ============================================================================
# 单专家路由
# ============================================================================

class ExpertRouter:
    """Expert routing based on keyword matching and GLM semantic analysis"""

    def __init__(self):
        self.config = get_config()
        self._route_cache = LRUCache(maxsize=256)
        self._expert_team = self.config._config.get("experts", {})

    def route_by_keywords(self, user_input: str) -> str:
        """Route to expert based on keyword matching"""
        input_lower = user_input.lower()
        scores = {}

        for expert_key, expert_config in self._expert_team.items():
            keywords = expert_config.get("keywords", [])
            score = sum(1 for kw in keywords if kw.lower() in input_lower)
            if score > 0:
                scores[expert_key] = score

        if scores:
            return max(scores, key=scores.get)

        return "pm"

    async def route_by_glm(self, user_input: str) -> str:
        """Route to expert using GLM semantic analysis"""
        if len(user_input) < 10:
            return self.route_by_keywords(user_input)

        cache_key = user_input[:200]
        cached = self._route_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            from .llm import LLMClient

            llm = LLMClient("glm-v")
            prompt = f"""判断以下用户问题属于哪个专家领域，只回复一个词：
- coder：编程开发、代码、函数、bug、技术实现
- reasoner：数学推理、逻辑证明、算法分析、复杂计算
- academic：学术论文、公式推导、文献综述、研究方法、LaTeX、定理证明
- chinese：中文写作、文章、报告、文案、邮件
- vision：图片理解、截图分析、视觉
- pm：任务分析、计划制定、翻译、通用问答、解释说明
- knowledge：百科知识、事实查询、翻译、其他
- devops：运维、部署、系统管理、容器、SSH、监控
- security：安全分析、漏洞评估、加固、审计
- data：数据分析、统计建模、可视化、数据清洗

用户问题：{user_input[:300]}

只回复上面列出的一个词，不要回复其他任何内容。"""

            response = await llm.chat(
                system_prompt="你是 ZeroAI 路由分析器，只负责把用户问题分类到一个专家。严格只输出一个英文标识词，不要做解释。",
                user_prompt=prompt,
                temperature=0.01,
                max_tokens=10,
                stream=False
            )

            if response is None:
                return "pm"

            result = response.strip().lower()

            valid_keys = set(self._expert_team.keys())
            for vk in valid_keys:
                if vk in result:
                    self._route_cache.set(cache_key, vk)
                    return vk

            expert_key = self.route_by_keywords(user_input)
            self._route_cache.set(cache_key, expert_key)
            return expert_key

        except Exception:
            expert_key = self.route_by_keywords(user_input)
            self._route_cache.set(cache_key, expert_key)
            return expert_key

    def get_expert_config(self, expert_key: str) -> Dict:
        """Get configuration for a specific expert"""
        return self.config.get_expert_config(expert_key)

    def get_all_experts(self) -> Dict[str, Dict]:
        """Get all expert configurations"""
        return self._expert_team.copy()

    def clear_cache(self):
        """Clear the routing cache"""
        self._route_cache = LRUCache(maxsize=256)


# ============================================================================
# 混合模式：多专家协作系统
# ============================================================================

class HybridExpertSystem:
    """混合思考模式：多专家协作处理同一问题

    流程：GLM分析 → 专家并行回答 → 去重 → GLM汇总

    从 tui_agent.py 的 _run_hybrid_turn 迁移并模块化。
    TUI 显示逻辑由调用方处理，本类只负责数据流。
    """

    def __init__(self):
        self.config = get_config()
        self.router = ExpertRouter()
        self.llm_client = get_multi_model_client()
        self._expert_memory: Dict[str, List[Dict]] = {}

        # 从配置加载参数
        hybrid_cfg = self.config.get_hybrid_config()
        self.max_parallel_experts = hybrid_cfg.get("max_parallel_experts", 3)
        self.expert_max_chars = hybrid_cfg.get("expert_max_chars", 800)
        self.dedup_similarity_threshold = hybrid_cfg.get("dedup_similarity_threshold", 0.7)
        self.memory_turns = hybrid_cfg.get("memory_turns", 3)
        self.enable_collab_chain = hybrid_cfg.get("enable_collab_chain", False)

    async def select_experts(self, user_input: str) -> List[str]:
        """GLM 分析任务，选择多个专家

        Returns:
            专家 key 列表（最多 max_parallel_experts 个）
        """
        # 短消息用关键词路由
        if len(user_input) < 10:
            return [self.router.route_by_keywords(user_input)]

        try:
            llm = LLMClient("glm-v")
            analyze_prompt = f"""请分析以下用户需求，判断需要哪些专家协作处理。
可用专家：
- coder: 编程开发
- reasoner: 深度推理/数学
- academic: 学术研究/公式推导/论文写作
- chinese: 中文写作/文案
- knowledge: 通用知识/翻译
- vision: 图片理解
- devops: 运维/部署/系统管理/容器/SSH
- security: 安全分析/漏洞评估/加固
- data: 数据分析/统计/可视化

用户需求：{user_input[:500]}

请只回复专家标识，用逗号分隔（最多{self.max_parallel_experts}个），例如：coder,reasoner
不要回复其他内容。"""

            response = await llm.chat(
                system_prompt="你是 ZeroAI 路由分析器，只负责判断用户问题应分配给哪些专家。严格按要求只输出专家标识，不要做任何解释。",
                user_prompt=analyze_prompt,
                temperature=0.1,
                max_tokens=30,
                stream=False,
                timeout=30,
            )

            if response is None:
                return [self.router.route_by_keywords(user_input)]

            analysis = response.strip().lower()
        except Exception:
            analysis = ""

        # 解析专家列表
        expert_keys = []
        valid_experts = set(self.router.get_all_experts().keys())
        for part in analysis.replace("，", ",").split(","):
            part = part.strip()
            if part in valid_experts and part not in ("pm",) and part not in expert_keys:
                expert_keys.append(part)

        if not expert_keys:
            expert_keys = [self.router.route_by_keywords(user_input)]

        # 限制并行度
        return expert_keys[:self.max_parallel_experts]

    async def call_expert(
        self,
        expert_key: str,
        user_input: str,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> Optional[str]:
        """调用单个专家（含专家记忆）

        Args:
            expert_key: 专家标识
            user_input: 用户输入
            temperature: 温度
            stream: 是否流式

        Returns:
            专家回答，或 None 表示失败
        """
        expert_config = self.config.get_expert_config(expert_key)
        system_prompt = expert_config.get(
            "system_prompt",
            "你是 ZeroAI 专家团队成员，从专业角度回答用户问题。"
        )

        # 构建消息（含专家记忆）
        messages = [{"role": "system", "content": system_prompt}]
        memory = self._expert_memory.get(expert_key, [])
        messages.extend(memory)
        messages.append({"role": "user", "content": user_input})

        try:
            response = await self.llm_client.call_expert(
                expert_key=expert_key,
                messages=messages,
                temperature=temperature,
                max_tokens=2000,
                stream=stream,
            )
        except Exception:
            return None

        if response is None:
            return None

        # 截断过长的回答
        if self.expert_max_chars > 0 and len(response) > self.expert_max_chars:
            response = truncate_expert_response(response, self.expert_max_chars)

        # 更新专家记忆
        if self.memory_turns > 0:
            memory = self._expert_memory.get(expert_key, [])
            memory.append({"role": "user", "content": user_input})
            memory.append({"role": "assistant", "content": response})
            max_msgs = self.memory_turns * 2
            if len(memory) > max_msgs:
                memory = memory[-max_msgs:]
            self._expert_memory[expert_key] = memory

        return response

    async def call_experts_parallel(
        self,
        expert_keys: List[str],
        user_input: str,
        temperature: float = 0.7,
    ) -> List[Dict[str, str]]:
        """多专家并行调用

        Returns:
            [{"expert": key, "label": label, "content": text}, ...]
            失败的专家不会出现在结果中
        """
        tasks = {}
        for ek in expert_keys:
            tasks[ek] = self.call_expert(ek, user_input, temperature, stream=False)

        results = []
        for ek, task in tasks.items():
            try:
                content = await task
                if content:
                    expert_cfg = self.config.get_expert_config(ek)
                    results.append({
                        "expert": ek,
                        "label": expert_cfg.get("label", ek),
                        "content": content,
                    })
            except Exception:
                continue

        return results

    async def call_experts_chain(
        self,
        expert_keys: List[str],
        user_input: str,
        temperature: float = 0.7,
    ) -> List[Dict[str, str]]:
        """协作链模式：专家依次回答，每个后续专家能看到前一位专家的结果

        场景：coder 写代码 → reasoner 审查逻辑 → academic 补充引用

        Returns:
            [{"expert": key, "label": label, "content": text}, ...]
        """
        results = []
        prev_content = None

        for ek in expert_keys:
            if prev_content:
                chain_input = (
                    f"用户原始问题：{user_input}\n\n"
                    f"前一位专家（{results[-1]['expert']}）的回答：\n{prev_content}\n\n"
                    f"请基于以上信息，从你的专业角度补充和完善回答。"
                )
            else:
                chain_input = user_input

            content = await self.call_expert(ek, chain_input, temperature, stream=False)
            if content:
                expert_cfg = self.config.get_expert_config(ek)
                results.append({
                    "expert": ek,
                    "label": expert_cfg.get("label", ek),
                    "content": content,
                })
                prev_content = content

        return results

    def dedup_responses(
        self,
        responses: List[Dict[str, str]],
    ) -> Tuple[List[Dict[str, str]], List[Tuple[str, str, float]]]:
        """基于 Jaccard 相似度去重

        Returns:
            (unique_responses, dedup_skipped)
            - unique_responses: 去重后的回答列表
            - dedup_skipped: 被去重的记录 [(expert_a, expert_b, similarity), ...]
        """
        if self.dedup_similarity_threshold <= 0 or len(responses) <= 1:
            return responses, []

        unique = [responses[0]]
        skipped = []
        for resp in responses[1:]:
            is_dup = False
            for kept in unique:
                sim = jaccard_similarity(resp["content"], kept["content"])
                if sim >= self.dedup_similarity_threshold:
                    is_dup = True
                    skipped.append((resp["expert"], kept["expert"], round(sim, 2)))
                    break
            if not is_dup:
                unique.append(resp)

        return unique, skipped

    async def summarize_responses(
        self,
        responses: List[Dict[str, str]],
        user_input: str,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> Optional[str]:
        """GLM 汇总多专家回答

        Args:
            responses: 专家回答列表
            user_input: 原始用户输入
            temperature: 温度
            stream: 是否流式

        Returns:
            汇总后的最终回复
        """
        if not responses:
            return None
        if len(responses) == 1:
            return responses[0]["content"]

        summary_prompt = "以下是多位专家的回答，请综合整理为一份完整、连贯的回复：\n\n"
        for resp in responses:
            summary_prompt += f"【{resp['expert']}】\n{resp['content'][:2000]}\n\n"
        summary_prompt += "\n请综合以上内容，给出最终回复。"

        try:
            llm = LLMClient("glm-v")
            return await llm.chat(
                system_prompt=(
                    "你是 ZeroAI 项目经理，负责将多位专家的回答综合整理为完整、连贯的最终回复。"
                    "保留关键信息，消除重复，按用户问题逻辑组织。"
                ),
                user_prompt=summary_prompt,
                temperature=temperature,
                max_tokens=2000,
                stream=stream,
                timeout=60,
            )
        except Exception:
            # 汇总失败，返回第一个专家的回答
            return responses[0]["content"] if responses else None

    async def run_hybrid_turn(
        self,
        user_input: str,
        temperature: float = 0.7,
        stream: bool = False,
        log_func: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """执行一次完整的混合思考流程

        流程：选择专家 → 并行/链式调用 → 去重 → 汇总

        Args:
            user_input: 用户输入
            temperature: 温度
            stream: 是否流式
            log_func: 日志回调

        Returns:
            {
                "experts": [选中的专家 keys],
                "responses": [专家回答列表],
                "dedup_skipped": [去重记录],
                "final_response": 最终汇总回复,
            }
        """
        # 1. 选择专家
        expert_keys = await self.select_experts(user_input)
        if log_func:
            labels = []
            for ek in expert_keys:
                cfg = self.config.get_expert_config(ek)
                labels.append(f"{cfg.get('label', ek)}")
            log_func(f"需要 {len(expert_keys)} 位专家协作：{', '.join(labels)}")

        # 2. 调用专家（并行或链式）
        if self.enable_collab_chain and len(expert_keys) > 1:
            if log_func:
                log_func("协作链模式：专家依次回答并传递结果")
            responses = await self.call_experts_chain(expert_keys, user_input, temperature)
        else:
            responses = await self.call_experts_parallel(expert_keys, user_input, temperature)

        if not responses:
            return {
                "experts": expert_keys,
                "responses": [],
                "dedup_skipped": [],
                "final_response": "（所有专家调用失败，请检查网络或 API Key 后重试）",
            }

        # 3. 去重
        responses, dedup_skipped = self.dedup_responses(responses)
        if dedup_skipped and log_func:
            dedup_parts = [f"{a}≈{b}({s})" for a, b, s in dedup_skipped]
            log_func(f"去重：{', '.join(dedup_parts)} 已合并")

        # 4. 汇总
        if len(responses) == 1:
            final = responses[0]["content"]
        else:
            final = await self.summarize_responses(responses, user_input, temperature, stream)

        return {
            "experts": expert_keys,
            "responses": responses,
            "dedup_skipped": dedup_skipped,
            "final_response": final or "",
        }

    def clear_expert_memory(self, expert_key: Optional[str] = None):
        """清除专家记忆

        Args:
            expert_key: 指定专家 key，None 表示清除所有
        """
        if expert_key:
            self._expert_memory.pop(expert_key, None)
        else:
            self._expert_memory.clear()


# ============================================================================
# 全局实例管理
# ============================================================================

_expert_router: Optional[ExpertRouter] = None
_hybrid_system: Optional[HybridExpertSystem] = None


def get_expert_router() -> ExpertRouter:
    """Get global expert router instance"""
    global _expert_router
    if _expert_router is None:
        _expert_router = ExpertRouter()
    return _expert_router


def get_hybrid_system() -> HybridExpertSystem:
    """Get global hybrid expert system instance"""
    global _hybrid_system
    if _hybrid_system is None:
        _hybrid_system = HybridExpertSystem()
    return _hybrid_system


def route_expert(user_input: str) -> str:
    """Route user input to appropriate expert (sync wrapper)"""
    router = get_expert_router()
    return router.route_by_keywords(user_input)


async def route_expert_async(user_input: str) -> str:
    """Route user input to appropriate expert (async)"""
    router = get_expert_router()
    return await router.route_by_glm(user_input)
