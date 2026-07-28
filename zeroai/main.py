"""ZeroAI 统一入口

从 tui_agent.py 行14566-14614 迁移并增强。
支持两种 UI 模式：
- textual: 原始 Textual UI（tui_agent.py 中的 ZeroAI App）
- zeroai-tui: C/Zig 加速的新 TUI 框架

用法：
    python -m zeroai                    # 默认 textual UI
    python -m zeroai --ui textual       # 显式指定 textual UI
    python -m zeroai --ui zeroai-tui    # 使用 C/Zig 加速 TUI
    python -m zeroai --expert coder     # 直接指定专家
    python -m zeroai --version          # 显示版本号
"""
import os
import sys
import argparse


def _ensure_project_root_in_path():
    """确保项目根目录在 sys.path 中"""
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_script_dir)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)


def _get_version() -> str:
    """获取版本号"""
    try:
        # 优先从 pyproject.toml 读取
        import tomllib  # Python 3.11+
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(_script_dir)
        pyproject_path = os.path.join(_project_root, "pyproject.toml")
        if os.path.exists(pyproject_path):
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                return data.get("project", {}).get("version", "unknown")
    except Exception:
        pass
    return "1.1.3"  # 回退版本号


def main():
    """ZeroAI 主入口"""
    _ensure_project_root_in_path()

    version = _get_version()
    parser = argparse.ArgumentParser(
        description="ZeroAI - 终端 AI 编程助手（多专家协作·语音对话·文档生成·安全审计）",
        prog="zeroai",
    )
    parser.add_argument("--ui", choices=["textual", "zeroai-tui"], default="textual",
                        help="UI framework to use (default: textual)")
    parser.add_argument("--expert", type=str, help="Direct expert mode (skip routing)")
    parser.add_argument("--version", action="version", version=f"ZeroAI v{version}")
    args, unknown = parser.parse_known_args()

    try:
        if args.ui == "zeroai-tui":
            # 使用 zeroai-tui UI（C/Zig 加速）
            try:
                _script_dir = os.path.dirname(os.path.abspath(__file__))
                _project_root = os.path.dirname(_script_dir)
                _tui_dir = os.path.join(_project_root, "zeroai-tui")
                if _tui_dir not in sys.path:
                    sys.path.insert(0, _tui_dir)

                from zeroai_tui.integration import ZeroAIIntegration

                print(f"Starting ZeroAI v{version} with zeroai-tui (C-accelerated)...")
                print("Press Ctrl+C to exit")
                print()

                integration = ZeroAIIntegration()
                integration.start()

            except ImportError as e:
                print(f"zeroai-tui not available: {e}")
                print("Falling back to Textual UI...")
                args.ui = "textual"

        if args.ui == "textual":
            # 使用 Textual UI
            # 优先从 zeroai.tui 包导入（包装模式），回退到 tui_agent.py 直接导入
            try:
                from zeroai.tui.app import ZeroAI
                _import_source = "zeroai.tui.app"
            except ImportError:
                from tui_agent import ZeroAI
                _import_source = "tui_agent"

            print(f"Starting ZeroAI v{version} (UI: {_import_source})...", file=sys.stderr)
            app = ZeroAI()
            app.title = f"ZeroAI v{version}"
            app.run()
    finally:
        # 程序退出时清理运行时缓存
        try:
            from zeroai.core.runtime import runtime_cache
            runtime_cache.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
