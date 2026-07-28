"""模型管理与客户端工厂

迁移来源：tui_agent.py 行 1645-1739

提供：
- get_active_model_info：获取当前实际使用的模型信息（考虑工作模式）
- _load_custom_models / _save_custom_models：自定义模型持久化
- detect_ollama_models：探测本地 Ollama 可用模型
- CURRENT_MODEL_KEY / BUILTIN_MODEL_KEYS：当前与内置模型 key
- get_model_display_name：模型显示名
- get_client / get_model_name / get_model_label：当前模型客户端/名称/标签

依赖关系：
- constants.py：MODEL_CONFIGS, WORK_MODE
- secrets.py：_deobfuscate, _obfuscate
- paths.py：CUSTOM_MODELS_FILE

注意：
- 模块加载时自动调用 _load_custom_models()（与 tui_agent.py 行 1707 行为一致）
- 兼容旧代码：初始化全局 client 和 MODEL（与 tui_agent.py 行 1738-1739 一致）
- WORK_MODE 在 constants.py 中定义为模块级变量，本模块通过 set_work_mode 间接修改
"""
import json
import urllib.request

from openai import OpenAI

from .constants import MODEL_CONFIGS, WORK_MODE
from .secrets import _deobfuscate, _obfuscate
from .paths import CUSTOM_MODELS_FILE


def get_active_model_info() -> dict:
    """获取当前实际使用的模型信息（考虑工作模式）"""
    # 延迟读取 WORK_MODE（可能被 set_work_mode 修改）
    from . import constants as _const
    work_mode = _const.WORK_MODE
    if work_mode == "manual":
        cfg = MODEL_CONFIGS.get(CURRENT_MODEL_KEY, MODEL_CONFIGS["glm"])
        return {"base_url": cfg["base_url"], "api_key": cfg["api_key"],
                "model": cfg["model"], "label": cfg["label"]}
    elif work_mode == "expert":
        # 专家模式下返回默认专家（实际路由在 _run_turn 中动态决定）
        cfg = MODEL_CONFIGS["glm"]
        return {"base_url": cfg["base_url"], "api_key": cfg["api_key"],
                "model": cfg["model"], "label": "专家模式"}
    else:  # hybrid
        cfg = MODEL_CONFIGS["glm"]
        return {"base_url": cfg["base_url"], "api_key": cfg["api_key"],
                "model": cfg["model"], "label": "混合思考"}


def _load_custom_models():
    """从 CUSTOM_MODELS_FILE 加载用户自定义模型，合并到 MODEL_CONFIGS"""
    if CUSTOM_MODELS_FILE.exists():
        try:
            data = json.loads(CUSTOM_MODELS_FILE.read_text(encoding="utf-8"))
            for key, cfg in data.items():
                if key not in MODEL_CONFIGS:
                    # 反混淆 api_key
                    if cfg.get("api_key"):
                        cfg["api_key"] = _deobfuscate(cfg["api_key"])
                    MODEL_CONFIGS[key] = cfg
        except Exception:
            pass


def _save_custom_models():
    """保存自定义模型到 CUSTOM_MODELS_FILE（api_key 混淆存储）"""
    custom = {k: v for k, v in MODEL_CONFIGS.items() if k not in ("glm", "glm-v", "openrouter", "ollama")}
    try:
        safe = {}
        for k, v in custom.items():
            safe[k] = dict(v)
            if safe[k].get("api_key"):
                safe[k]["api_key"] = _obfuscate(safe[k]["api_key"])
        CUSTOM_MODELS_FILE.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def detect_ollama_models() -> list:
    """探测本地 Ollama 服务可用的模型列表

    Returns:
        模型 id 列表（如 ["gemma4:latest", "llama3:latest"]）；
        连接失败返回空列表。
    """
    try:
        req = urllib.request.Request("http://localhost:11434/v1/models",
                                     headers={"User-Agent": "ZeroAI"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if mid:
                models.append(mid)
        return models
    except Exception:
        return []


# 模块加载时自动加载自定义模型（与 tui_agent.py 行 1707 行为一致）
_load_custom_models()

# 当前使用的模型 key（默认 glm，TUI 层可切换）
CURRENT_MODEL_KEY = "glm"

# 内置模型 key 集合（与 _save_custom_models 保持一致）
BUILTIN_MODEL_KEYS = ("glm", "glm-v", "openrouter", "ollama")


def get_model_display_name(model_key: str) -> str:
    """获取模型显示名：内置显示"内置模型"，自定义显示真实名称"""
    if model_key in BUILTIN_MODEL_KEYS:
        return "内置模型"
    return MODEL_CONFIGS.get(model_key, {}).get("label", model_key)


def get_client():
    """获取当前模型的 OpenAI 客户端（同步）"""
    cfg = MODEL_CONFIGS[CURRENT_MODEL_KEY]
    return OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])


def get_model_name():
    """获取当前模型名"""
    return MODEL_CONFIGS[CURRENT_MODEL_KEY]["model"]


def get_model_label():
    """获取当前模型显示名（考虑工作模式）"""
    from . import constants as _const
    work_mode = _const.WORK_MODE
    if work_mode == "expert":
        return "专家模式"
    elif work_mode == "hybrid":
        return "混合思考"
    return MODEL_CONFIGS[CURRENT_MODEL_KEY]["label"]


def set_current_model_key(key: str):
    """切换当前模型 key（供 TUI 层调用）

    Args:
        key: MODEL_CONFIGS 中的键
    """
    global CURRENT_MODEL_KEY
    if key in MODEL_CONFIGS:
        CURRENT_MODEL_KEY = key


# 兼容旧代码：初始化全局 client 和 MODEL（与 tui_agent.py 行 1738-1739 一致）
client = get_client()
MODEL = get_model_name()
