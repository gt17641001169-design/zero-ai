"""
zeroai-tui 完整测试脚本
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def main():
    print("=" * 60)
    print("zeroai-tui 完整测试")
    print("=" * 60)
    print()
    
    tests = [
        ("基础模块导入", test_imports),
        ("C扩展加载", test_c_extension),
        ("终端操作", test_terminal),
        ("渲染引擎", test_renderer),
        ("组件系统", test_components),
        ("Chat界面", test_chat),
        ("集成模块", test_integration),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        print(f"[测试] {name}...", end=" ")
        try:
            if test_func():
                print("✓")
                passed += 1
            else:
                print("✗")
                failed += 1
        except Exception as e:
            print(f"✗ ({e})")
            failed += 1
    
    print()
    print("=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    if failed == 0:
        print()
        print("所有测试通过!")
        print()
        print("运行方式:")
        print("  python test_zeroai_tui.py")
    
    return failed == 0


def test_imports():
    """测试模块导入"""
    import zeroai_tui
    import zeroai_tui.renderer
    import zeroai_tui.terminal
    import zeroai_tui.components
    return True


def test_c_extension():
    """测试C扩展"""
    from zeroai_tui.renderer import HAS_C_RENDERER
    return HAS_C_RENDERER


def test_terminal():
    """测试终端操作"""
    from zeroai_tui.terminal import Terminal
    
    # 获取终端大小
    cols, rows = Terminal.get_size()
    assert cols > 0 and rows > 0
    
    return True


def test_renderer():
    """测试渲染引擎"""
    from zeroai_tui.renderer import Renderer, RenderBuffer, Style
    from zeroai_tui.terminal import Color
    
    # 创建渲染器
    renderer = Renderer()
    assert renderer.cols > 0 and renderer.rows > 0
    
    # 测试写入
    renderer.clear()
    renderer.write(0, 0, "Hello", Style(bold=True, fg=Color.CYAN))
    
    # 测试缓冲区操作
    buffer = RenderBuffer(80, 24)
    buffer.write(0, 0, "Test", Style())
    
    return True


def test_components():
    """测试组件系统"""
    from zeroai_tui.components import Component, Text, Box, Input, ScrollView
    from zeroai_tui.rich_components import Markdown, CodeBlock, StatusLine
    
    # 创建组件
    text = Text("Hello")
    assert text.content == "Hello"
    
    box = Box(children=[text])
    assert len(box.children) == 1
    
    return True


def test_chat():
    """测试Chat界面"""
    from zeroai_tui.zai_chat import ZeroAIChat, ChatMessage
    
    # 创建Chat应用
    app = ZeroAIChat()
    assert app is not None
    
    # 创建消息
    msg = ChatMessage("user", "Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"
    
    return True


def test_integration():
    """测试集成模块"""
    from zeroai_tui.integration import ZeroAIIntegration, create_demo_app
    
    # 创建集成实例
    integration = ZeroAIIntegration()
    assert integration is not None
    
    # 创建Demo应用
    app = create_demo_app()
    assert app is not None
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
