"""ZeroAI - Terminal AI Assistant for Research & Engineering"""
import sys
from pathlib import Path

# Add package to path if needed
package_dir = Path(__file__).parent
if str(package_dir.parent) not in sys.path:
    sys.path.insert(0, str(package_dir.parent))

from .core.config import get_config, load_config
from .core.expert import (
    get_expert_router, get_hybrid_system,
    route_expert, route_expert_async,
    ExpertRouter, HybridExpertSystem,
)
from .core.llm import LLMClient, get_multi_model_client
from .core.context import (
    get_context_manager,
    cleanup_context, compress_context, cleanup_and_compress,
    estimate_tokens, get_model_context_limit,
)
from .tools.base import Tool, ToolRegistry, ToolError, ToolExecutionError, ToolValidationError
from .utils.platform import is_windows, is_linux, is_macos, get_platform


__version__ = "1.1.3"
__author__ = "ZeroAI"


def init(config_path: str = None):
    """Initialize ZeroAI with configuration"""
    if config_path:
        load_config(config_path)
    else:
        # Try to find config.yaml in package directory
        config_file = package_dir / "config.yaml"
        if config_file.exists():
            load_config(str(config_file))


def get_version() -> str:
    """Get ZeroAI version"""
    return __version__


# Auto-initialize on import
if not get_config()._config:
    init()
