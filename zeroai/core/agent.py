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


__all__ = [
    "ReActPlanner",
    "AgentLoop",
    "PLANNER_SYSTEM_PROMPT",
    "get_agent_loop",
    "reset_agent_loop",
]
