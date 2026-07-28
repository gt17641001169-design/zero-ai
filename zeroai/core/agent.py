"""ReAct Agent 核心 - 观察-思考-行动 循环

将 ZeroAI 从"工具调用循环"升级为真正的 Agent Loop：
    观察（Observation）→ 思考（Thought）→ 行动（Action）→ 再观察 → ...

核心设计：
1. ReActPlanner：让 LLM 先思考下一步做什么，输出结构化 JSON
2. AgentLoop：驱动 观察→思考→行动 循环，支持自我纠错
3. 完全复用现有 TOOLS / TOOL_MAP 工具体系，无需改造工具层
4. 可选开关：通过 ZeroAI.react_enabled 启用，不破坏原有 _run_turn_impl

依赖：
- zeroai.core.llm.LLMClient：调用 LLM
- zeroai.tools.registry.TOOL_MAP：工具函数映射

参考论文：ReAct: Synergizing Reasoning and Acting in Language Models (Yao et al., 2022)
参考实现：OpenHands / SWE-agent / smolagents
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import inspect
from dataclasses import dataclass, field, asdict
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .llm import LLMClient


# ============================================================================
# ReAct Planner - 让 LLM 先思考再行动
# ============================================================================

PLANNER_SYSTEM_PROMPT = """你是 ZeroAI 的任务规划器（ReAct Planner）。

你的职责是分析当前状态，决定下一步行动。严格输出 JSON，格式如下：

```json
{
  "thought": "简短说明你的思考过程（1-2句话）",
  "need_more_info": false,
  "next_action": {
    "type": "tool_call" | "final_answer" | "ask_user",
    "tool": "工具名（仅 type=tool_call 时需要）",
    "args": {"参数名": "参数值"},
    "answer": "最终回答（仅 type=final_answer 时需要）",
    "question": "向用户提问（仅 type=ask_user 时需要）"
  },
  "task_complete": false
}
```

决策规则：
1. 如果用户问题可以直接回答（无需外部信息），选择 final_answer
2. 如果需要读取文件/执行命令/检查系统等，选择 tool_call
3. 如果信息不足无法继续，选择 ask_user
4. 工具调用后，根据结果决定继续调用工具还是给出最终答案
5. 任务完成后设置 task_complete=true

重要：只输出 JSON，不要输出其他任何内容。不要用 markdown 代码块包裹。"""


PLANNER_USER_TEMPLATE = """## 用户请求
{user_input}

## 当前观察
{observation}

## 可用工具
{tools_summary}

## 已执行步骤
{history}

## 任务状态
请决定下一步行动。"""


class ReActPlanner:
    """ReAct 规划器：让 LLM 思考下一步做什么

    输出结构化 JSON，包含：
    - thought：思考过程
    - next_action：下一步行动（tool_call / final_answer / ask_user）
    - task_complete：任务是否完成
    """

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        model_key: str = "glm",
        temperature: float = 0.2,
        max_tokens: int = 800,
    ):
        """初始化规划器

        Args:
            llm: LLM 客户端，为 None 时用 model_key 创建
            model_key: 模型标识（llm 为 None 时生效）
            temperature: 低温度保证规划稳定性
            max_tokens: 规划输出 token 上限
        """
        self.llm = llm or LLMClient(model_key)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._tools_summary_cache: Optional[str] = None
        self._tools_cache_key: Optional[str] = None

    def _build_tools_summary(self, tools: List[Dict[str, Any]]) -> str:
        """构建工具摘要供规划器参考

        只提取 name 和 description 的第一行，避免 token 暴涨。
        """
        cache_key = str(hash((t.get("function", {}).get("name", "") for t in tools)))
        if self._tools_cache_key == cache_key and self._tools_summary_cache:
            return self._tools_summary_cache

        lines = []
        for t in tools:
            fn = t.get("function", {})
            name = fn.get("name", "")
            desc = fn.get("description", "").split("\n")[0][:100]
            lines.append(f"- {name}: {desc}")
        self._tools_summary_cache = "\n".join(lines)
        self._tools_cache_key = cache_key
        return self._tools_summary_cache

    def _build_observation(
        self,
        messages: List[Dict[str, Any]],
        retriever: Optional[Callable[[str], List[str]]] = None,
        user_input: str = "",
    ) -> str:
        """构建当前观察：最近对话 + 工具结果 + RAG 检索

        Args:
            messages: 当前对话历史
            retriever: RAG 检索函数，输入查询返回相关文档片段
            user_input: 用户原始输入（用于 RAG 检索）

        Returns:
            观察文本
        """
        parts = []

        # 1. RAG 检索项目上下文
        if retriever and user_input:
            try:
                docs = retriever(user_input)
                if docs:
                    parts.append("### 项目上下文（RAG 检索）")
                    for i, doc in enumerate(docs[:3], 1):
                        parts.append(f"[{i}] {doc[:300]}")
                    parts.append("")
            except Exception:
                pass

        # 2. 最近对话历史（最后 6 条，避免 token 暴涨）
        recent = messages[-6:] if len(messages) > 6 else messages
        parts.append("### 最近对话")
        for msg in recent:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            content_str = str(content)[:500]
            parts.append(f"[{role}] {content_str}")
        parts.append("")

        return "\n".join(parts)

    def _build_history(self, executed_steps: List[Dict[str, Any]]) -> str:
        """构建已执行步骤摘要"""
        if not executed_steps:
            return "（尚无）"
        lines = []
        for i, step in enumerate(executed_steps, 1):
            thought = step.get("thought", "")[:80]
            action_type = step.get("action_type", "?")
            if action_type == "tool_call":
                tool_name = step.get("tool_name", "?")
                result_preview = str(step.get("result", ""))[:120]
                lines.append(f"{i}. 思考: {thought}")
                lines.append(f"   行动: 调用 {tool_name}")
                lines.append(f"   结果: {result_preview}")
            elif action_type == "final_answer":
                lines.append(f"{i}. 思考: {thought}")
                lines.append(f"   行动: 给出最终答案")
            else:
                lines.append(f"{i}. {thought}")
        return "\n".join(lines)

    async def plan_next(
        self,
        user_input: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        executed_steps: List[Dict[str, Any]],
        retriever: Optional[Callable[[str], List[str]]] = None,
    ) -> Dict[str, Any]:
        """规划下一步行动

        Returns:
            {
                "thought": "思考过程",
                "next_action": {
                    "type": "tool_call" | "final_answer" | "ask_user",
                    "tool": "...", "args": {...},
                    "answer": "...", "question": "..."
                },
                "task_complete": bool
            }
        """
        observation = self._build_observation(messages, retriever, user_input)
        tools_summary = self._build_tools_summary(tools)
        history = self._build_history(executed_steps)

        user_prompt = PLANNER_USER_TEMPLATE.format(
            user_input=user_input[:500],
            observation=observation,
            tools_summary=tools_summary,
            history=history,
        )

        try:
            response = await self.llm.chat(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False,
                timeout=30,
            )
        except Exception as e:
            return {
                "thought": f"规划器调用失败: {e}",
                "next_action": {"type": "final_answer", "answer": f"规划失败: {e}"},
                "task_complete": True,
            }

        if response is None:
            return {
                "thought": "规划器无响应",
                "next_action": {"type": "final_answer", "answer": "规划器无响应"},
                "task_complete": True,
            }

        return self._parse_plan(response)

    def _parse_plan(self, response: str) -> Dict[str, Any]:
        """解析规划器输出为结构化 JSON

        兼容多种输出格式：
        1. 纯 JSON
        2. JSON 外包裹 ```json ... ```
        3. JSON 前后有多余文字
        """
        text = response.strip()

        # 去除 markdown 代码块
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        # 尝试直接解析
        try:
            return self._validate_plan(json.loads(text))
        except json.JSONDecodeError:
            pass

        # 尝试提取第一个 JSON 对象
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return self._validate_plan(json.loads(match.group(0)))
            except json.JSONDecodeError:
                pass

        # 解析失败，作为最终答案返回原文
        return {
            "thought": "规划器输出解析失败，直接使用原文作为回答",
            "next_action": {"type": "final_answer", "answer": response},
            "task_complete": True,
        }

    def _validate_plan(self, data: Any) -> Dict[str, Any]:
        """校验并规范化规划输出"""
        if not isinstance(data, dict):
            return {
                "thought": "规划输出非 dict",
                "next_action": {"type": "final_answer", "answer": str(data)},
                "task_complete": True,
            }

        thought = data.get("thought", "")
        task_complete = bool(data.get("task_complete", False))
        next_action = data.get("next_action", {})

        if not isinstance(next_action, dict):
            next_action = {"type": "final_answer", "answer": str(next_action)}

        action_type = next_action.get("type", "final_answer")
        if action_type not in ("tool_call", "final_answer", "ask_user"):
            action_type = "final_answer"
            next_action["type"] = action_type

        # tool_call 必须有 tool 名
        if action_type == "tool_call" and not next_action.get("tool"):
            return {
                "thought": "规划器要求 tool_call 但未提供工具名，转为最终答案",
                "next_action": {"type": "final_answer", "answer": thought or "无法确定要调用的工具"},
                "task_complete": True,
            }

        return {
            "thought": thought,
            "next_action": next_action,
            "task_complete": task_complete,
        }


# ============================================================================
# Agent Loop - 驱动 观察→思考→行动 循环
# ============================================================================

class AgentLoop:
    """ReAct Agent 循环驱动器

    流程：
        1. 观察：收集当前状态（对话历史 + RAG 检索）
        2. 思考：ReActPlanner 决定下一步
        3. 行动：执行工具调用 / 给出最终答案 / 向用户提问
        4. 回到 1，直到任务完成或达到最大步数

    特性：
    - 自我纠错：工具调用失败时，把错误反馈给规划器，让它换方案
    - 步数限制：防止无限循环
    - 回调机制：每一步都通知 UI 层更新显示
    - 完全复用现有 TOOL_MAP，无需改造工具
    """

    def __init__(
        self,
        planner: Optional[ReActPlanner] = None,
        tool_map: Optional[Dict[str, Callable]] = None,
        tools_schema: Optional[List[Dict[str, Any]]] = None,
        max_steps: int = 8,
        retriever: Optional[Callable[[str], List[str]]] = None,
    ):
        """初始化 Agent Loop

        Args:
            planner: ReAct 规划器，为 None 时用默认 GLM
            tool_map: 工具名->函数映射，为 None 时从 registry 导入
            tools_schema: 工具 schema 列表，为 None 时从 registry 导入
            max_steps: 单轮对话最大步数
            retriever: RAG 检索函数
        """
        self.planner = planner or ReActPlanner()
        if tool_map is None or tools_schema is None:
            from zeroai.tools.registry import TOOL_MAP, TOOLS
            self.tool_map = tool_map or TOOL_MAP
            self.tools_schema = tools_schema or TOOLS
        else:
            self.tool_map = tool_map
            self.tools_schema = tools_schema
        self.max_steps = max_steps
        self.retriever = retriever

        # 回调钩子（UI 层注册）
        self.on_thought: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_tool_call: Optional[Callable[[str, Dict], Awaitable[None]]] = None
        self.on_tool_result: Optional[Callable[[str, str], Awaitable[None]]] = None
        self.on_final_answer: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_error: Optional[Callable[[str], Awaitable[None]]] = None
        self.is_stopped: Optional[Callable[[], bool]] = None

    def _check_stopped(self) -> bool:
        """检查是否被用户中断"""
        if self.is_stopped:
            try:
                return bool(self.is_stopped())
            except Exception:
                return False
        return False

    async def _execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """执行工具调用，返回结果字符串

        自动过滤模型幻觉的无效参数。
        """
        fn = self.tool_map.get(name)
        if fn is None:
            return f"[错误] 未知工具: {name}"

        # 过滤无效参数
        try:
            valid_params = set(inspect.signature(fn).parameters)
            safe_args = {k: v for k, v in args.items() if k in valid_params}
            extra = set(args.keys()) - valid_params
        except (ValueError, TypeError):
            safe_args = args
            extra = set()

        # 执行（支持同步和异步函数）
        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(**safe_args)
            else:
                result = fn(**safe_args)
            result_str = str(result)
            if extra:
                result_str += f"\n[提示：忽略多余参数 {extra}]"
            return result_str
        except TypeError as e:
            return f"[参数错误] {e}"
        except Exception as e:
            return f"[执行错误] {type(e).__name__}: {e}"

    async def run(
        self,
        user_input: str,
        messages: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """运行 Agent 循环

        Args:
            user_input: 用户输入
            messages: 当前对话历史（会被修改）

        Returns:
            (final_answer, executed_steps)
        """
        executed_steps: List[Dict[str, Any]] = []
        final_answer = ""

        for step in range(1, self.max_steps + 1):
            if self._check_stopped():
                break

            # 1. 思考：规划下一步
            plan = await self.planner.plan_next(
                user_input=user_input,
                messages=messages,
                tools=self.tools_schema,
                executed_steps=executed_steps,
                retriever=self.retriever,
            )

            thought = plan.get("thought", "")
            action = plan.get("next_action", {})
            task_complete = plan.get("task_complete", False)

            if self.on_thought:
                try:
                    await self.on_thought(f"[步 {step}] {thought}")
                except Exception:
                    pass

            action_type = action.get("type", "final_answer")

            # 2. 行动
            if action_type == "tool_call":
                tool_name = action.get("tool", "")
                tool_args = action.get("args", {})
                if not isinstance(tool_args, dict):
                    tool_args = {}

                if self.on_tool_call:
                    try:
                        await self.on_tool_call(tool_name, tool_args)
                    except Exception:
                        pass

                result = await self._execute_tool(tool_name, tool_args)

                if self.on_tool_result:
                    try:
                        await self.on_tool_result(tool_name, result)
                    except Exception:
                        pass

                step_record = {
                    "thought": thought,
                    "action_type": "tool_call",
                    "tool_name": tool_name,
                    "args": tool_args,
                    "result": result,
                }
                executed_steps.append(step_record)

                # 把工具结果加入对话历史，让规划器下一轮能看到
                messages.append({
                    "role": "assistant",
                    "content": f"[调用工具 {tool_name}] {thought}",
                })
                messages.append({
                    "role": "user",
                    "content": f"[工具结果 {tool_name}] {result[:1500]}",
                })

            elif action_type == "ask_user":
                question = action.get("question", "需要更多信息")
                final_answer = question
                if self.on_final_answer:
                    try:
                        await self.on_final_answer(question)
                    except Exception:
                        pass
                break

            else:  # final_answer
                final_answer = action.get("answer", thought or "")
                step_record = {
                    "thought": thought,
                    "action_type": "final_answer",
                    "answer": final_answer,
                }
                executed_steps.append(step_record)

                if self.on_final_answer:
                    try:
                        await self.on_final_answer(final_answer)
                    except Exception:
                        pass
                break

            if task_complete:
                break

        if not final_answer:
            final_answer = "已达到最大步数，未能完成任务。"
            if self.on_final_answer:
                try:
                    await self.on_final_answer(final_answer)
                except Exception:
                    pass

        return final_answer, executed_steps


# ============================================================================
# 便捷工厂函数
# ============================================================================

_agent_loop_instance: Optional[AgentLoop] = None


def get_agent_loop(
    model_key: str = "glm",
    max_steps: int = 8,
    retriever: Optional[Callable[[str], List[str]]] = None,
) -> AgentLoop:
    """获取 AgentLoop 单例

    Args:
        model_key: 规划器使用的模型
        max_steps: 最大步数
        retriever: RAG 检索函数

    Returns:
        AgentLoop 实例
    """
    global _agent_loop_instance
    if _agent_loop_instance is None or retriever is not None:
        planner = ReActPlanner(model_key=model_key)
        _agent_loop_instance = AgentLoop(
            planner=planner,
            max_steps=max_steps,
            retriever=retriever,
        )
    return _agent_loop_instance


def reset_agent_loop() -> None:
    """重置 AgentLoop 单例（配置变更后调用）"""
    global _agent_loop_instance
    _agent_loop_instance = None


# ============================================================================
# 阶段 1 增强：思维链 / 多步规划 / 反思 / 并行 / 摘要
# 以下代码为增量追加，不修改上方任何既有类与函数，保证向后兼容
# ============================================================================


# ----------------------------------------------------------------------------
# 1.1 思维链数据结构（Thought + Plan）—— 让 Agent 推理过程可追溯、可持久化
# ----------------------------------------------------------------------------

@dataclass
class Thought:
    """单步思考记录

    Agent Loop 每一步都会生成一个 Thought，完整记录：
    - 当前思考内容
    - 采取的行动类型（工具调用 / 最终回答 / 向用户提问 / 反思 / 计划）
    - 工具名、参数、结果
    - 反思内容（如果发生错误并触发 Reflexion）
    - 时间戳

    设计目的：让 Agent 的推理链可追溯、可可视化、可持久化，
    而非黑盒。TUI 层可通过 on_thought_chain 回调实时流式展示。
    """

    step: int
    thought: str
    action_type: str  # tool_call / final_answer / ask_user / reflect / plan
    tool_name: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    reflection: Optional[str] = None
    success: bool = True
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（用于持久化/JSON 序列化）"""
        return asdict(self)

    def brief(self) -> str:
        """生成简短摘要（用于 TUI 显示）"""
        parts = [f"[步{self.step}] {self.thought[:100]}"]
        if self.action_type == "tool_call" and self.tool_name:
            parts.append(f"  → 调用 {self.tool_name}({self.args})")
            if self.result:
                parts.append(f"  ← {self.result[:80]}")
        elif self.action_type == "reflect":
            parts.append(f"  ⟳ 反思: {self.reflection[:100] if self.reflection else ''}")
        elif self.action_type == "final_answer":
            parts.append(f"  ✓ 完成")
        return "\n".join(parts)


@dataclass
class Plan:
    """多步执行计划（Plan-and-Execute 模式）

    由 PlanAndExecutePlanner.create_plan() 生成，包含：
    - goal: 任务目标
    - steps: 有序步骤列表，每个步骤含 tool/args/reason/depends_on
    - expected_output: 预期输出描述
    - 支持依赖关系：depends_on 指向前面步骤的索引列表

    执行时按顺序进行，某步依赖前序步骤的结果时，
    会把前序结果注入该步的 args（通过 {prev_result_N} 占位符）。
    """

    goal: str
    steps: List[Dict[str, Any]]  # [{tool, args, reason, depends_on: [int]}, ...]
    expected_output: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def step_count(self) -> int:
        return len(self.steps)


# ----------------------------------------------------------------------------
# 1.3 反思引擎（Reflexion）—— 工具失败时让 LLM 复盘并换方案
# ----------------------------------------------------------------------------

REFLECTION_SYSTEM_PROMPT = """你是 ZeroAI 的反思引擎。

当一个工具调用失败时，你需要：
1. 分析失败原因（参数错误？工具选择错误？环境问题？）
2. 给出改进建议（换工具？修参数？换方案？）

严格输出 JSON：
```json
{
  "failure_reason": "失败原因分析（1-2句）",
  "suggestion_type": "retry" | "change_args" | "change_tool" | "give_up",
  "new_tool": "新工具名（仅 change_tool 时需要）",
  "new_args": {"参数名": "新参数值"},
  "explanation": "改进方案说明"
}
```

只输出 JSON，不要输出其他内容。"""


class ReflexionEngine:
    """反思引擎：工具调用失败时让 LLM 复盘原因并给出改进方案

    参考：Reflexion: Language Agents with Verbal Reinforcement Learning (Shinn et al., 2023)

    使用方式：
        engine = ReflexionEngine(llm)
        reflection = await engine.reflect(tool_name, args, error, history)
        if reflection["suggestion_type"] == "change_args":
            new_args = reflection["new_args"]
            # 用新参数重试
    """

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        model_key: str = "glm",
        max_reflections: int = 2,
    ):
        """初始化反思引擎

        Args:
            llm: LLM 客户端
            model_key: 模型标识
            max_reflections: 单个工具最大反思次数（避免无限重试）
        """
        self.llm = llm or LLMClient(model_key)
        self.max_reflections = max_reflections
        self._reflection_count: Dict[str, int] = {}  # tool_name -> count

    async def reflect(
        self,
        tool_name: str,
        args: Dict[str, Any],
        error: str,
        history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """对一次失败的工具调用进行反思

        Args:
            tool_name: 失败的工具名
            args: 调用参数
            error: 错误信息
            history: 之前执行过的步骤

        Returns:
            {
                "failure_reason": "...",
                "suggestion_type": "retry" | "change_args" | "change_tool" | "give_up",
                "new_tool": "...",
                "new_args": {...},
                "explanation": "..."
            }
        """
        # 检查反思次数
        count = self._reflection_count.get(tool_name, 0)
        if count >= self.max_reflections:
            return {
                "failure_reason": f"已达到最大反思次数 {self.max_reflections}",
                "suggestion_type": "give_up",
                "new_tool": None,
                "new_args": {},
                "explanation": "放弃重试，转入最终答案",
            }
        self._reflection_count[tool_name] = count + 1

        # 构建反思 prompt
        history_text = "\n".join(
            f"  {i+1}. {h.get('action_type','?')}: {h.get('thought','')[:80]}"
            for i, h in enumerate(history[-5:])
        )
        user_prompt = (
            f"## 失败的工具调用\n"
            f"工具: {tool_name}\n"
            f"参数: {json.dumps(args, ensure_ascii=False)}\n"
            f"错误: {error[:500]}\n\n"
            f"## 之前的执行历史\n{history_text or '（无）'}\n\n"
            f"## 任务\n分析失败原因，给出改进建议。"
        )

        try:
            response = await self.llm.chat(
                system_prompt=REFLECTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=500,
                stream=False,
                timeout=20,
            )
        except Exception as e:
            return {
                "failure_reason": f"反思引擎调用失败: {e}",
                "suggestion_type": "give_up",
                "new_tool": None,
                "new_args": {},
                "explanation": "反思失败，放弃重试",
            }

        if response is None:
            return {
                "failure_reason": "反思引擎无响应",
                "suggestion_type": "give_up",
                "new_tool": None,
                "new_args": {},
                "explanation": "无响应",
            }

        return self._parse_reflection(response)

    def _parse_reflection(self, response: str) -> Dict[str, Any]:
        """解析反思输出"""
        text = response.strip()
        # 去除 markdown 代码块
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        suggestion = data.get("suggestion_type", "give_up")
        if suggestion not in ("retry", "change_args", "change_tool", "give_up"):
            suggestion = "give_up"

        return {
            "failure_reason": data.get("failure_reason", "未知原因"),
            "suggestion_type": suggestion,
            "new_tool": data.get("new_tool"),
            "new_args": data.get("new_args", {}),
            "explanation": data.get("explanation", ""),
        }

    def reset(self) -> None:
        """重置反思计数（新一轮对话开始时调用）"""
        self._reflection_count.clear()


# ----------------------------------------------------------------------------
# 1.5 工具结果摘要器 —— 长输出用小模型摘要，避免上下文爆炸
# ----------------------------------------------------------------------------

SUMMARIZER_SYSTEM_PROMPT = """你是 ZeroAI 的工具结果摘要器。

将长文本工具输出压缩为简短摘要，保留关键信息：
1. 命令输出：保留关键状态/错误/数据，去掉冗余日志
2. 文件内容：保留核心结构（函数名/类名/关键逻辑），去掉细节
3. 搜索结果：保留标题和摘要，去掉重复内容

输出格式：纯文本摘要，不超过 500 字。不要加 markdown 标题。"""


class ToolResultSummarizer:
    """工具结果摘要器：超长输出用 LLM 摘要后入对话历史

    作用：避免长输出（如 systeminfo、大文件内容）撑爆上下文窗口。
    阈值由 summarize_threshold 控制，默认 1500 字符。
    """

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        model_key: str = "glm",
        summarize_threshold: int = 1500,
        target_length: int = 500,
    ):
        """初始化

        Args:
            llm: LLM 客户端（建议用快速小模型）
            model_key: 模型标识
            summarize_threshold: 触发摘要的最小输出长度（字符数）
            target_length: 摘要目标长度
        """
        self.llm = llm or LLMClient(model_key)
        self.summarize_threshold = summarize_threshold
        self.target_length = target_length

    async def maybe_summarize(
        self,
        result: str,
        tool_name: str,
        query: str = "",
    ) -> str:
        """如果结果过长，用 LLM 摘要；否则原样返回

        Args:
            result: 工具返回的原始结果
            tool_name: 工具名（用于上下文）
            query: 用户原始查询（帮助摘要聚焦）

        Returns:
            摘要后的结果（或原始结果）
        """
        if not result or len(result) <= self.summarize_threshold:
            return result

        try:
            user_prompt = (
                f"## 工具: {tool_name}\n"
                f"## 用户意图: {query[:200]}\n"
                f"## 原始输出（{len(result)} 字符）\n"
                f"{result[:4000]}"  # 截断，避免摘要本身超长
            )
            summary = await self.llm.chat(
                system_prompt=SUMMARIZER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=self.target_length * 2,
                stream=False,
                timeout=15,
            )
            if summary and summary.strip():
                return f"[摘要] {summary.strip()}"
        except Exception:
            pass

        # 摘要失败，截断原结果
        return result[:self.summarize_threshold] + f"\n...[已截断，共 {len(result)} 字符]"


# ----------------------------------------------------------------------------
# 1.2 多步规划器（Plan-and-Execute）—— 先制定完整计划再执行
# ----------------------------------------------------------------------------

PLANNER_PLAN_SYSTEM_PROMPT = """你是 ZeroAI 的任务规划器（Plan-and-Execute 模式）。

你的职责是把用户的复杂任务拆解为有序的执行计划。严格输出 JSON：

```json
{
  "goal": "任务目标简述",
  "steps": [
    {
      "tool": "工具名",
      "args": {"参数名": "参数值"},
      "reason": "为什么这一步",
      "depends_on": []
    }
  ],
  "expected_output": "预期最终输出"
}
```

规则：
1. steps 必须是有序数组，按执行顺序排列
2. depends_on 是数组，元素为前序步骤的索引（从0开始），表示依赖关系
    - 例如 "depends_on": [0] 表示这一步需要用到第0步的结果
    - 无依赖则留空数组 []
3. args 中可用占位符 {prev_result_0}、{prev_result_1} 引用前序步骤结果
    - 例如 "args": {"path": "{prev_result_0}"} 表示路径来自第0步输出
4. 只输出 JSON，不要其他内容。"""


class PlanAndExecutePlanner:
    """多步规划器：先制定完整计划，再逐步执行

    与 ReActPlanner（逐步反应）互补：
    - ReActPlanner：每步都问 LLM 下一步做什么，灵活但慢
    - PlanAndExecutePlanner：先一次性制定完整计划，再执行，快但需要 replan

    参考：Plan-and-Solve Prompting (Wang et al., 2023)

    用法：
        planner = PlanAndExecutePlanner(llm)
        plan = await planner.create_plan(user_input, tools, retriever)
        # 执行 plan.steps...
        # 如果某步失败，调用 planner.replan() 重新规划剩余步骤
    """

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        model_key: str = "glm",
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ):
        self.llm = llm or LLMClient(model_key)
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _build_tools_summary(self, tools: List[Dict[str, Any]]) -> str:
        """构建工具摘要"""
        lines = []
        for t in tools:
            fn = t.get("function", {})
            name = fn.get("name", "")
            desc = fn.get("description", "").split("\n")[0][:100]
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def _build_context(
        self,
        retriever: Optional[Callable[[str], List[str]]],
        user_input: str,
    ) -> str:
        """构建 RAG 上下文"""
        if not retriever or not user_input:
            return "（无）"
        try:
            docs = retriever(user_input)
            if docs:
                return "\n".join(d[:300] for d in docs[:3])
        except Exception:
            pass
        return "（无）"

    async def create_plan(
        self,
        user_input: str,
        tools: List[Dict[str, Any]],
        retriever: Optional[Callable[[str], List[str]]] = None,
    ) -> Plan:
        """制定完整执行计划

        Args:
            user_input: 用户请求
            tools: 可用工具 schema
            retriever: RAG 检索函数

        Returns:
            Plan 对象
        """
        tools_summary = self._build_tools_summary(tools)
        context = self._build_context(retriever, user_input)

        user_prompt = (
            f"## 用户请求\n{user_input[:800]}\n\n"
            f"## 可用工具\n{tools_summary}\n\n"
            f"## 项目上下文\n{context}\n\n"
            f"## 任务\n制定完整的执行计划。"
        )

        try:
            response = await self.llm.chat(
                system_prompt=PLANNER_PLAN_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False,
                timeout=30,
            )
        except Exception as e:
            return Plan(goal=user_input, steps=[], expected_output=f"规划失败: {e}")

        if response is None:
            return Plan(goal=user_input, steps=[], expected_output="规划器无响应")

        return self._parse_plan(response, user_input)

    def _parse_plan(self, response: str, user_input: str) -> Plan:
        """解析规划输出"""
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        steps = data.get("steps", [])
        if not isinstance(steps, list):
            steps = []

        # 校验每个 step
        valid_steps = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            tool = s.get("tool", "")
            if not tool:
                continue
            valid_steps.append({
                "tool": tool,
                "args": s.get("args", {}) if isinstance(s.get("args"), dict) else {},
                "reason": s.get("reason", ""),
                "depends_on": [
                    int(d) for d in s.get("depends_on", [])
                    if isinstance(d, (int, str)) and str(d).isdigit()
                ],
            })

        return Plan(
            goal=data.get("goal", user_input),
            steps=valid_steps,
            expected_output=data.get("expected_output", ""),
        )

    async def replan(
        self,
        original_plan: Plan,
        executed_steps: List[Dict[str, Any]],
        failure: str,
        tools: List[Dict[str, Any]],
    ) -> Plan:
        """根据失败情况重新规划剩余步骤

        Args:
            original_plan: 原计划
            executed_steps: 已执行的步骤（含结果）
            failure: 失败原因
            tools: 可用工具

        Returns:
            新的 Plan（只含剩余步骤）
        """
        executed_text = "\n".join(
            f"  {i+1}. {s.get('tool','?')} → {str(s.get('result',''))[:100]}"
            for i, s in enumerate(executed_steps)
        )
        tools_summary = self._build_tools_summary(tools)

        user_prompt = (
            f"## 原始目标\n{original_plan.goal}\n\n"
            f"## 已执行步骤\n{executed_text or '（无）'}\n\n"
            f"## 失败原因\n{failure[:300]}\n\n"
            f"## 可用工具\n{tools_summary}\n\n"
            f"## 任务\n根据失败情况，重新规划剩余步骤。"
        )

        try:
            response = await self.llm.chat(
                system_prompt=PLANNER_PLAN_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False,
                timeout=30,
            )
        except Exception:
            return Plan(goal=original_plan.goal, steps=[], expected_output="重规划失败")

        if response is None:
            return Plan(goal=original_plan.goal, steps=[], expected_output="重规划无响应")

        return self._parse_plan(response, original_plan.goal)


# ----------------------------------------------------------------------------
# 1.4 + 全部增强集成：AdvancedAgentLoop
# ----------------------------------------------------------------------------

class AdvancedAgentLoop(AgentLoop):
    """增强版 Agent Loop

    在基础 AgentLoop 之上集成：
    1. 思维链可视化：thought_chain 完整记录每步思考，on_thought_chain 实时回调
    2. 多步规划：支持 Plan-and-Execute 模式（先制定计划再执行）
    3. 自我反思：工具失败时 ReflexionEngine 复盘并换方案重试
    4. 并行工具调用：规划器返回多个无依赖工具时用 asyncio.gather 并行
    5. 工具结果摘要：长输出自动用小模型摘要

    用法：
        loop = AdvancedAgentLoop(
            enable_plan=True,        # 启用多步规划
            enable_reflexion=True,   # 启用反思
            enable_parallel=True,    # 启用并行
            enable_summarize=True,   # 启用摘要
        )
        loop.on_thought_chain = my_callback  # 思维链回调
        final_answer, steps, chain = await loop.run_with_chain(user_input, messages)

    向后兼容：
        - 不传任何增强参数时，行为与基础 AgentLoop 一致
        - run() 方法保持原有签名，返回 (answer, steps)
        - 新功能通过 run_with_chain() 暴露
    """

    def __init__(
        self,
        planner: Optional[ReActPlanner] = None,
        tool_map: Optional[Dict[str, Callable]] = None,
        tools_schema: Optional[List[Dict[str, Any]]] = None,
        max_steps: int = 8,
        retriever: Optional[Callable[[str], List[str]]] = None,
        # 增强参数
        enable_plan: bool = False,
        enable_reflexion: bool = True,
        enable_parallel: bool = True,
        enable_summarize: bool = True,
        reflexion_engine: Optional[ReflexionEngine] = None,
        summarizer: Optional[ToolResultSummarizer] = None,
        plan_planner: Optional[PlanAndExecutePlanner] = None,
    ):
        """初始化增强版 Agent Loop

        Args:
            planner: 基础 ReAct 规划器
            tool_map / tools_schema / max_steps / retriever: 同 AgentLoop
            enable_plan: 启用 Plan-and-Execute 模式
            enable_reflexion: 启用反思重试
            enable_parallel: 启用并行工具调用
            enable_summarize: 启用结果摘要
            reflexion_engine: 自定义反思引擎
            summarizer: 自定义摘要器
            plan_planner: 自定义多步规划器
        """
        super().__init__(
            planner=planner,
            tool_map=tool_map,
            tools_schema=tools_schema,
            max_steps=max_steps,
            retriever=retriever,
        )
        self.enable_plan = enable_plan
        self.enable_reflexion = enable_reflexion
        self.enable_parallel = enable_parallel
        self.enable_summarize = enable_summarize

        # 延迟初始化（只在启用时创建，避免浪费 API 资源）
        self.reflexion_engine = reflexion_engine or (
            ReflexionEngine() if enable_reflexion else None
        )
        self.summarizer = summarizer or (
            ToolResultSummarizer() if enable_summarize else None
        )
        self.plan_planner = plan_planner or (
            PlanAndExecutePlanner() if enable_plan else None
        )

        # 思维链（每轮 run 清空）
        self.thought_chain: List[Thought] = []

        # 新增回调：思维链更新
        self.on_thought_chain: Optional[Callable[[Thought], Awaitable[None]]] = None

    async def _emit_thought(self, thought: Thought) -> None:
        """推送思维链更新"""
        self.thought_chain.append(thought)
        if self.on_thought_chain:
            try:
                await self.on_thought_chain(thought)
            except Exception:
                pass
        # 同时触发基础 on_thought 回调
        if self.on_thought:
            try:
                await self.on_thought(thought.brief())
            except Exception:
                pass

    async def _execute_tool_with_enhancements(
        self,
        name: str,
        args: Dict[str, Any],
        user_input: str = "",
    ) -> Tuple[str, bool]:
        """增强版工具执行：含反思重试 + 结果摘要

        Returns:
            (result, success)
        """
        max_attempts = (self.reflexion_engine.max_reflections + 1) if self.reflexion_engine else 1
        current_name = name
        current_args = args

        for attempt in range(max_attempts):
            # 执行工具
            result = await self._execute_tool(current_name, current_args)
            success = not result.startswith("[错误]") and not result.startswith("[参数错误]") and not result.startswith("[执行错误]")

            if success:
                # 成功：摘要压缩
                if self.summarizer and self.enable_summarize:
                    result = await self.summarizer.maybe_summarize(
                        result, current_name, user_input
                    )
                return result, True

            # 失败：如果不启用反思，直接返回
            if not self.reflexion_engine or not self.enable_reflexion:
                return result, False

            # 触发反思
            reflection = await self.reflexion_engine.reflect(
                tool_name=current_name,
                args=current_args,
                error=result,
                history=[t.to_dict() for t in self.thought_chain],
            )

            thought = Thought(
                step=len(self.thought_chain) + 1,
                thought=f"工具 {current_name} 失败，反思中...",
                action_type="reflect",
                tool_name=current_name,
                args=current_args,
                result=result,
                reflection=reflection.get("failure_reason", ""),
                success=False,
            )
            await self._emit_thought(thought)

            suggestion = reflection.get("suggestion_type", "give_up")
            if suggestion == "give_up":
                return result, False
            elif suggestion == "retry":
                continue  # 用相同参数重试
            elif suggestion == "change_args":
                new_args = reflection.get("new_args", {})
                if isinstance(new_args, dict):
                    current_args = {**current_args, **new_args}
            elif suggestion == "change_tool":
                new_tool = reflection.get("new_tool", "")
                if new_tool and new_tool in self.tool_map:
                    current_name = new_tool

        return result, False

    async def _execute_tools_parallel(
        self,
        tool_calls: List[Dict[str, Any]],
        user_input: str = "",
    ) -> List[Tuple[str, str, bool]]:
        """并行执行多个无依赖的工具调用

        Args:
            tool_calls: [{"tool": "...", "args": {...}}, ...]

        Returns:
            [(tool_name, result, success), ...]
        """
        async def _run_one(call: Dict[str, Any]) -> Tuple[str, str, bool]:
            name = call.get("tool", "")
            args = call.get("args", {})
            result, success = await self._execute_tool_with_enhancements(
                name, args, user_input
            )
            return name, result, success

        results = await asyncio.gather(*[_run_one(c) for c in tool_calls])
        return list(results)

    async def run_with_chain(
        self,
        user_input: str,
        messages: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]], List[Thought]]:
        """运行 Agent 循环（增强版），返回完整思维链

        Args:
            user_input: 用户输入
            messages: 对话历史

        Returns:
            (final_answer, executed_steps, thought_chain)
        """
        self.thought_chain = []
        if self.reflexion_engine:
            self.reflexion_engine.reset()

        # 分支：Plan-and-Execute 模式
        if self.enable_plan and self.plan_planner:
            return await self._run_with_plan(user_input, messages)

        # 默认：ReAct 模式（增强版）
        return await self._run_react_enhanced(user_input, messages)

    async def _run_react_enhanced(
        self,
        user_input: str,
        messages: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]], List[Thought]]:
        """增强版 ReAct 循环"""
        executed_steps: List[Dict[str, Any]] = []
        final_answer = ""

        for step in range(1, self.max_steps + 1):
            if self._check_stopped():
                break

            # 1. 思考
            plan = await self.planner.plan_next(
                user_input=user_input,
                messages=messages,
                tools=self.tools_schema,
                executed_steps=executed_steps,
                retriever=self.retriever,
            )

            thought_text = plan.get("thought", "")
            action = plan.get("next_action", {})
            task_complete = plan.get("task_complete", False)
            action_type = action.get("type", "final_answer")

            # 检查是否为并行工具调用（规划器返回 next_action.type=parallel_tool_calls）
            is_parallel = action_type == "parallel_tool_calls"
            tool_calls_list = action.get("tool_calls", []) if is_parallel else []

            thought = Thought(
                step=step,
                thought=thought_text,
                action_type="parallel_tool_calls" if is_parallel else action_type,
                tool_name=action.get("tool") if not is_parallel else None,
                args=action.get("args", {}) if not is_parallel else {},
            )
            await self._emit_thought(thought)

            # 2. 行动
            if action_type == "tool_call":
                tool_name = action.get("tool", "")
                tool_args = action.get("args", {})
                if not isinstance(tool_args, dict):
                    tool_args = {}

                if self.on_tool_call:
                    try:
                        await self.on_tool_call(tool_name, tool_args)
                    except Exception:
                        pass

                result, success = await self._execute_tool_with_enhancements(
                    tool_name, tool_args, user_input
                )

                if self.on_tool_result:
                    try:
                        await self.on_tool_result(tool_name, result)
                    except Exception:
                        pass

                # 更新 thought
                thought.result = result
                thought.success = success

                executed_steps.append({
                    "thought": thought_text,
                    "action_type": "tool_call",
                    "tool_name": tool_name,
                    "args": tool_args,
                    "result": result,
                    "success": success,
                })

                messages.append({
                    "role": "assistant",
                    "content": f"[调用工具 {tool_name}] {thought_text}",
                })
                messages.append({
                    "role": "user",
                    "content": f"[工具结果 {tool_name}] {result[:1500]}",
                })

            elif is_parallel and self.enable_parallel:
                # 并行执行多个工具
                if self.on_tool_call:
                    for tc in tool_calls_list:
                        try:
                            await self.on_tool_call(tc.get("tool", ""), tc.get("args", {}))
                        except Exception:
                            pass

                results = await self._execute_tools_parallel(tool_calls_list, user_input)

                for name, result, success in results:
                    if self.on_tool_result:
                        try:
                            await self.on_tool_result(name, result)
                        except Exception:
                            pass
                    executed_steps.append({
                        "thought": thought_text,
                        "action_type": "tool_call",
                        "tool_name": name,
                        "args": next((tc.get("args", {}) for tc in tool_calls_list if tc.get("tool") == name), {}),
                        "result": result,
                        "success": success,
                    })
                    messages.append({
                        "role": "assistant",
                        "content": f"[并行调用 {name}]",
                    })
                    messages.append({
                        "role": "user",
                        "content": f"[工具结果 {name}] {result[:1500]}",
                    })

            elif action_type == "ask_user":
                question = action.get("question", "需要更多信息")
                final_answer = question
                thought.action_type = "ask_user"
                if self.on_final_answer:
                    try:
                        await self.on_final_answer(question)
                    except Exception:
                        pass
                break

            else:  # final_answer
                final_answer = action.get("answer", thought_text or "")
                thought.action_type = "final_answer"
                executed_steps.append({
                    "thought": thought_text,
                    "action_type": "final_answer",
                    "answer": final_answer,
                })
                if self.on_final_answer:
                    try:
                        await self.on_final_answer(final_answer)
                    except Exception:
                        pass
                break

            if task_complete:
                break

        if not final_answer:
            final_answer = "已达到最大步数，未能完成任务。"
            if self.on_final_answer:
                try:
                    await self.on_final_answer(final_answer)
                except Exception:
                    pass

        return final_answer, executed_steps, self.thought_chain

    async def _run_with_plan(
        self,
        user_input: str,
        messages: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]], List[Thought]]:
        """Plan-and-Execute 模式：先制定计划，再逐步执行

        流程：
        1. PlanAndExecutePlanner.create_plan() 制定完整计划
        2. 按顺序执行每个 step
        3. 某步失败时，调用 replan() 重新规划剩余步骤
        4. 全部完成后，让 LLM 基于所有结果生成最终答案
        """
        # 1. 制定计划
        plan = await self.plan_planner.create_plan(
            user_input=user_input,
            tools=self.tools_schema,
            retriever=self.retriever,
        )

        thought = Thought(
            step=1,
            thought=f"已制定计划：{plan.goal}（{plan.step_count()} 步）",
            action_type="plan",
        )
        await self._emit_thought(thought)

        if plan.step_count() == 0:
            # 规划失败，回退到 ReAct
            return await self._run_react_enhanced(user_input, messages)

        # 2. 逐步执行
        executed_steps: List[Dict[str, Any]] = []
        step_results: List[str] = []  # 每步的结果，供后续步骤引用
        final_answer = ""

        for idx, step_def in enumerate(plan.steps):
            if self._check_stopped():
                break

            tool_name = step_def.get("tool", "")
            raw_args = step_def.get("args", {})
            reason = step_def.get("reason", "")
            depends_on = step_def.get("depends_on", [])

            # 替换占位符 {prev_result_N}
            args = {}
            for k, v in raw_args.items():
                if isinstance(v, str):
                    replaced = v
                    for dep_idx in depends_on:
                        placeholder = f"{{prev_result_{dep_idx}}}"
                        if placeholder in replaced and dep_idx < len(step_results):
                            replaced = replaced.replace(placeholder, step_results[dep_idx][:500])
                    args[k] = replaced
                else:
                    args[k] = v

            thought = Thought(
                step=idx + 2,  # 第1步是 plan
                thought=f"执行步骤 {idx+1}/{plan.step_count()}: {reason}",
                action_type="tool_call",
                tool_name=tool_name,
                args=args,
            )
            await self._emit_thought(thought)

            if self.on_tool_call:
                try:
                    await self.on_tool_call(tool_name, args)
                except Exception:
                    pass

            result, success = await self._execute_tool_with_enhancements(
                tool_name, args, user_input
            )

            thought.result = result
            thought.success = success

            if self.on_tool_result:
                try:
                    await self.on_tool_result(tool_name, result)
                except Exception:
                    pass

            executed_steps.append({
                "thought": reason,
                "action_type": "tool_call",
                "tool_name": tool_name,
                "args": args,
                "result": result,
                "success": success,
            })
            step_results.append(result)

            messages.append({
                "role": "assistant",
                "content": f"[执行计划步骤 {idx+1}: {tool_name}] {reason}",
            })
            messages.append({
                "role": "user",
                "content": f"[工具结果 {tool_name}] {result[:1500]}",
            })

            # 失败时重规划
            if not success and self.reflexion_engine and self.enable_reflexion:
                new_plan = await self.plan_planner.replan(
                    original_plan=plan,
                    executed_steps=executed_steps,
                    failure=result,
                    tools=self.tools_schema,
                )
                if new_plan.step_count() > 0:
                    # 用新计划的剩余步骤替换未执行部分
                    plan.steps = new_plan.steps
                    thought = Thought(
                        step=idx + 3,
                        thought=f"重规划成功，剩余 {plan.step_count()} 步",
                        action_type="plan",
                    )
                    await self._emit_thought(thought)

        # 3. 让 LLM 基于所有结果生成最终答案
        if executed_steps:
            summary_parts = []
            for i, s in enumerate(executed_steps):
                summary_parts.append(f"步骤{i+1} ({s['tool_name']}): {str(s['result'])[:300]}")
            summary_text = "\n".join(summary_parts)

            try:
                final_answer = await self.planner.llm.chat(
                    system_prompt="你是 ZeroAI。根据工具执行结果，回答用户问题。简明扼要。",
                    user_prompt=f"## 用户问题\n{user_input}\n\n## 执行结果\n{summary_text}\n\n## 请给出最终答案",
                    temperature=0.5,
                    max_tokens=1000,
                    stream=False,
                    timeout=30,
                ) or "执行完成，但无法生成最终答案"
            except Exception as e:
                final_answer = f"执行完成，但生成答案失败: {e}"

            thought = Thought(
                step=len(self.thought_chain) + 1,
                thought="生成最终答案",
                action_type="final_answer",
                result=final_answer,
            )
            await self._emit_thought(thought)

            if self.on_final_answer:
                try:
                    await self.on_final_answer(final_answer)
                except Exception:
                    pass

        return final_answer, executed_steps, self.thought_chain


# ----------------------------------------------------------------------------
# 工厂函数（增强版）
# ----------------------------------------------------------------------------

_advanced_agent_loop_instance: Optional[AdvancedAgentLoop] = None


def get_advanced_agent_loop(
    model_key: str = "glm",
    max_steps: int = 8,
    retriever: Optional[Callable[[str], List[str]]] = None,
    enable_plan: bool = False,
    enable_reflexion: bool = True,
    enable_parallel: bool = True,
    enable_summarize: bool = True,
) -> AdvancedAgentLoop:
    """获取 AdvancedAgentLoop 单例

    Args:
        model_key: 模型标识
        max_steps: 最大步数
        retriever: RAG 检索函数
        enable_plan: 启用 Plan-and-Execute
        enable_reflexion: 启用反思
        enable_parallel: 启用并行
        enable_summarize: 启用摘要

    Returns:
        AdvancedAgentLoop 实例
    """
    global _advanced_agent_loop_instance
    if _advanced_agent_loop_instance is None or retriever is not None:
        planner = ReActPlanner(model_key=model_key)
        _advanced_agent_loop_instance = AdvancedAgentLoop(
            planner=planner,
            max_steps=max_steps,
            retriever=retriever,
            enable_plan=enable_plan,
            enable_reflexion=enable_reflexion,
            enable_parallel=enable_parallel,
            enable_summarize=enable_summarize,
        )
    return _advanced_agent_loop_instance


def reset_advanced_agent_loop() -> None:
    """重置 AdvancedAgentLoop 单例"""
    global _advanced_agent_loop_instance
    _advanced_agent_loop_instance = None


__all__ = [
    # 基础（向后兼容）
    "ReActPlanner",
    "AgentLoop",
    "PLANNER_SYSTEM_PROMPT",
    "get_agent_loop",
    "reset_agent_loop",
    # 阶段 1 增强
    "Thought",
    "Plan",
    "ReflexionEngine",
    "ToolResultSummarizer",
    "PlanAndExecutePlanner",
    "AdvancedAgentLoop",
    "REFLECTION_SYSTEM_PROMPT",
    "SUMMARIZER_SYSTEM_PROMPT",
    "PLANNER_PLAN_SYSTEM_PROMPT",
    "get_advanced_agent_loop",
    "reset_advanced_agent_loop",
]
