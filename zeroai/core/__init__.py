"""Core modules for ZeroAI

导出关键类和函数，便于上层调用：
    from zeroai.core import HybridExpertSystem, cleanup_and_compress, get_hybrid_system

本包包含两组模块：
1. 原有模块（config / expert / llm / context）：基于类的面向对象封装
2. 迁移模块（paths / runtime / constants / secrets / expert_route /
   context_compress / model_manager / response_utils）：从 tui_agent.py
   提取的纯函数版本，保持与原文件函数签名和行为完全一致。

迁移模块可通过子模块命名空间访问，避免与原有模块的同名符号冲突：
    from zeroai.core import expert_route, context_compress
    expert_route.route_expert(user_input)
    context_compress.compress_context(messages, limit)

各迁移模块的典型导出：
- paths：_get_desktop_dir, _resolve_save_path, _find_resource_dir, CONFIG_FILE
- runtime：RuntimeCache, runtime_cache, _is_stopped, _interruptible_await
- secrets：_obfuscate, _deobfuscate, _load_config, _get_api_key, _make_openai_client
- constants：MODEL_CONFIGS, EXPERT_TEAM, WORK_MODE, HYBRID_* 参数
- expert_route：route_expert, route_expert_glm, get_expert_config, LRUCache
- context_compress：cleanup_context, compress_context, cleanup_and_compress
- model_manager：get_client, get_model_name, get_model_label, detect_ollama_models
- response_utils：_strip_model_tokens, _parse_think_tags, _jaccard_similarity,
  _truncate_expert_response, _sanitize_identity_leak
"""
# ====== 原有模块导出（保持向后兼容）======
from .config import get_config, load_config
from .expert import (
    ExpertRouter, HybridExpertSystem, LRUCache,
    get_expert_router, get_hybrid_system,
    route_expert, route_expert_async,
    jaccard_similarity, truncate_expert_response,
)
from .llm import LLMClient, MultiModelClient, get_multi_model_client
from .context import (
    ContextManager, get_context_manager, create_context_manager,
    cleanup_context, compress_context, cleanup_and_compress,
    estimate_tokens, get_model_context_limit,
)

# ====== 迁移模块（从 tui_agent.py 提取的纯函数版本）======
# 以子模块形式导出，便于按命名空间访问同名符号
from . import paths
from . import runtime
from . import secrets
from . import constants
from . import expert_route
from . import context_compress
from . import model_manager
from . import response_utils

# 路径相关（无命名冲突，直接导出）
from .paths import (
    _get_desktop_dir,
    _resolve_save_path,
    _find_resource_dir,
    _ensure_user_dir,
    _get_resource_dir,
    CONFIG_FILE,
    CUSTOM_MODELS_FILE,
)

# 运行时缓存与中断控制
from .runtime import (
    RuntimeCache,
    runtime_cache,
    _is_stopped,
    _set_stop_flag,
    _interruptible_await,
    _interruptible_sleep,
)

# 密钥与配置持久化
from .secrets import (
    _obfuscate,
    _deobfuscate,
    _load_config,
    _save_config,
    _get_api_key,
    _load_proxy_config,
    _save_proxy_config,
    _is_proxy_enabled,
    _make_openai_client,
    PROXY_CONFIG,
)

# 配置常量与专家团队
from .constants import (
    MODEL_CONFIGS,
    EXPERT_TEAM,
    WORK_MODE,
    OR_BASE,
    OR_KEY,
    HYBRID_MAX_PARALLEL_EXPERTS,
    HYBRID_EXPERT_MAX_CHARS,
    HYBRID_DEDUP_SIMILARITY_THRESHOLD,
    EXPERT_MEMORY_TURNS,
    HYBRID_ENABLE_COLLAB_CHAIN,
    CHARS_PER_TOKEN,
    COMPRESS_THRESHOLD_RATIO,
    KEEP_RECENT_TURNS,
    CLEANUP_THRESHOLD_RATIO,
    CLEANUP_KEEP_RECENT_TURNS,
    TOOL_OUTPUT_SUMMARY_MAX_LEN,
    PERMISSION_LEVEL,
    MAX_FILE_SIZE,
    set_work_mode,
)

# 专家路由（新增独有函数；route_expert/LRUCache 与 .expert 同名，通过 expert_route 命名空间访问）
from .expert_route import (
    route_expert_glm,
    get_expert_config,
    _expert_route_cache,
    _is_openrouter_expert,
    _check_openrouter_circuit_breaker,
    _record_openrouter_failure,
    _record_openrouter_success,
)

# 上下文压缩（新增独有函数；cleanup_context/compress_context/cleanup_and_compress
# 与 .context 同名，通过 context_compress 命名空间访问）
from .context_compress import (
    _summarize_tool_output,
    _estimate_tokens,
    _get_model_context_limit,
    _truncate_messages_for_context,
    _model_supports_vision,
    _filter_messages_for_model,
    _split_messages_for_compress,
)

# 模型管理
from .model_manager import (
    get_active_model_info,
    detect_ollama_models,
    get_model_display_name,
    get_client,
    get_model_name,
    get_model_label,
    set_current_model_key,
    CURRENT_MODEL_KEY,
    BUILTIN_MODEL_KEYS,
)

# 响应处理工具
from .response_utils import (
    _strip_model_tokens,
    _parse_think_tags,
    _jaccard_similarity,
    _truncate_expert_response,
    _sanitize_identity_leak,
)

# ReAct Agent（观察-思考-行动循环）
from .agent import (
    ReActPlanner,
    AgentLoop,
    PLANNER_SYSTEM_PROMPT,
    get_agent_loop,
    reset_agent_loop,
    # 阶段 1 增强：思维链 / 多步规划 / 反思 / 并行 / 摘要
    Thought,
    Plan,
    ReflexionEngine,
    ToolResultSummarizer,
    PlanAndExecutePlanner,
    AdvancedAgentLoop,
    REFLECTION_SYSTEM_PROMPT,
    SUMMARIZER_SYSTEM_PROMPT,
    PLANNER_PLAN_SYSTEM_PROMPT,
    get_advanced_agent_loop,
    reset_advanced_agent_loop,
    # 阶段 B.4 多 Agent 协作
    AgentRole,
    MultiAgentCollaborator,
)

# 阶段 N：代码执行沙箱
from .sandbox import (
    CodeSafetyChecker,
    CodeSandbox,
    check_code_safety,
)

# 阶段 O：多 Agent 协作增强
from .agent_bus import (
    AgentMessage,
    MessageBus,
    Blackboard,
    get_message_bus,
    get_blackboard,
)
from .dynamic_roles import (
    RoleNode,
    CollaborationContext,
    RoleDependencyGraph,
    EnhancedMultiAgentCollaborator,
)

# 阶段 P：流式思维链 + 中断响应 + 进度跟踪
from .streaming import (
    ThoughtChunk,
    StreamingThoughtEmitter,
    InterruptionHandler,
    ToolCallProgress,
    ProgressTracker,
    get_streaming_emitter,
    get_interrupt_handler,
    get_progress_tracker,
    reset_streaming,
)

# 阶段 Q：项目代码知识图谱
from .code_knowledge_graph import (
    CodeNode,
    CodeEdge,
    CodeKnowledgeGraph,
    get_code_knowledge_graph,
    reset_code_knowledge_graph,
)

# 阶段 S：工具调用并行化
from .parallel_tools import (
    ToolCallRequest,
    ToolCallResult,
    ToolDependencyGraph,
    ResultMerger,
    ParallelToolScheduler,
    get_parallel_scheduler,
    reset_parallel_scheduler,
)

# 阶段 T：内存与性能优化
from .memory_optimizer import (
    VectorCompressor,
    CacheStats,
    UnifiedCacheManager,
    FileIndexEntry,
    IncrementalIndexer,
    ContextBudgetAllocator,
    get_unified_cache_manager,
    get_incremental_indexer,
    reset_memory_optimizers,
)

__all__ = [
    # 原有模块
    "get_config", "load_config",
    "ExpertRouter", "HybridExpertSystem", "LRUCache",
    "get_expert_router", "get_hybrid_system",
    "route_expert", "route_expert_async",
    "jaccard_similarity", "truncate_expert_response",
    "LLMClient", "MultiModelClient", "get_multi_model_client",
    "ContextManager", "get_context_manager", "create_context_manager",
    "cleanup_context", "compress_context", "cleanup_and_compress",
    "estimate_tokens", "get_model_context_limit",
    # 迁移模块（命名空间）
    "paths", "runtime", "secrets", "constants",
    "expert_route", "context_compress", "model_manager", "response_utils",
    # 路径
    "_get_desktop_dir", "_resolve_save_path", "_find_resource_dir",
    "_ensure_user_dir", "_get_resource_dir", "CONFIG_FILE", "CUSTOM_MODELS_FILE",
    # 运行时
    "RuntimeCache", "runtime_cache", "_is_stopped", "_set_stop_flag",
    "_interruptible_await", "_interruptible_sleep",
    # 密钥
    "_obfuscate", "_deobfuscate", "_load_config", "_save_config",
    "_get_api_key", "_load_proxy_config", "_save_proxy_config",
    "_is_proxy_enabled", "_make_openai_client", "PROXY_CONFIG",
    # 常量
    "MODEL_CONFIGS", "EXPERT_TEAM", "WORK_MODE", "OR_BASE", "OR_KEY",
    "HYBRID_MAX_PARALLEL_EXPERTS", "HYBRID_EXPERT_MAX_CHARS",
    "HYBRID_DEDUP_SIMILARITY_THRESHOLD", "EXPERT_MEMORY_TURNS",
    "HYBRID_ENABLE_COLLAB_CHAIN", "CHARS_PER_TOKEN",
    "COMPRESS_THRESHOLD_RATIO", "KEEP_RECENT_TURNS",
    "CLEANUP_THRESHOLD_RATIO", "CLEANUP_KEEP_RECENT_TURNS",
    "TOOL_OUTPUT_SUMMARY_MAX_LEN", "PERMISSION_LEVEL", "MAX_FILE_SIZE",
    "set_work_mode",
    # 专家路由
    "route_expert_glm", "get_expert_config", "_expert_route_cache",
    "_is_openrouter_expert", "_check_openrouter_circuit_breaker",
    "_record_openrouter_failure", "_record_openrouter_success",
    # 上下文压缩
    "_summarize_tool_output", "_estimate_tokens", "_get_model_context_limit",
    "_truncate_messages_for_context", "_model_supports_vision",
    "_filter_messages_for_model", "_split_messages_for_compress",
    # 模型管理
    "get_active_model_info", "detect_ollama_models", "get_model_display_name",
    "get_client", "get_model_name", "get_model_label", "set_current_model_key",
    "CURRENT_MODEL_KEY", "BUILTIN_MODEL_KEYS",
    # 响应处理
    "_strip_model_tokens", "_parse_think_tags", "_jaccard_similarity",
    "_truncate_expert_response", "_sanitize_identity_leak",
    # ReAct Agent
    "ReActPlanner", "AgentLoop", "PLANNER_SYSTEM_PROMPT",
    "get_agent_loop", "reset_agent_loop",
    # 阶段 1 增强
    "Thought", "Plan",
    "ReflexionEngine", "ToolResultSummarizer", "PlanAndExecutePlanner",
    "AdvancedAgentLoop",
    "REFLECTION_SYSTEM_PROMPT", "SUMMARIZER_SYSTEM_PROMPT",
    "PLANNER_PLAN_SYSTEM_PROMPT",
    "get_advanced_agent_loop", "reset_advanced_agent_loop",
    # 阶段 B.4 多 Agent 协作
    "AgentRole", "MultiAgentCollaborator",
    # 阶段 N：代码执行沙箱
    "CodeSafetyChecker", "CodeSandbox", "check_code_safety",
    # 阶段 O：多 Agent 协作增强
    "AgentMessage", "MessageBus", "Blackboard",
    "get_message_bus", "get_blackboard",
    "RoleNode", "CollaborationContext", "RoleDependencyGraph",
    "EnhancedMultiAgentCollaborator",
    # 阶段 P：流式思维链 + 中断响应 + 进度跟踪
    "ThoughtChunk", "StreamingThoughtEmitter", "InterruptionHandler",
    "ToolCallProgress", "ProgressTracker",
    "get_streaming_emitter", "get_interrupt_handler", "get_progress_tracker",
    "reset_streaming",
    # 阶段 Q：项目代码知识图谱
    "CodeNode", "CodeEdge", "CodeKnowledgeGraph",
    "get_code_knowledge_graph", "reset_code_knowledge_graph",
    # 阶段 S：工具调用并行化
    "ToolCallRequest", "ToolCallResult", "ToolDependencyGraph",
    "ResultMerger", "ParallelToolScheduler",
    "get_parallel_scheduler", "reset_parallel_scheduler",
    # 阶段 T：内存与性能优化
    "VectorCompressor", "CacheStats", "UnifiedCacheManager",
    "FileIndexEntry", "IncrementalIndexer", "ContextBudgetAllocator",
    "get_unified_cache_manager", "get_incremental_indexer", "reset_memory_optimizers",
]
