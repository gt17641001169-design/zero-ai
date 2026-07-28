"""
ZeroAI Integration Test
"""
import sys
import os

# Add paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_integration():
    """Test zeroai-tui integration"""
    print("=" * 60)
    print("ZeroAI Integration Test")
    print("=" * 60)
    print()
    
    tests = [
        ("Import zeroai_tui", test_import),
        ("Import zai_chat", test_zai_chat),
        ("Import integration", test_integration_module),
        ("Create ZeroAIChat", test_create_chat),
        ("Create ChatMessage", test_create_message),
        ("Markdown rendering", test_markdown),
        ("Code highlighting", test_highlight),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        print(f"[Test] {name}...")
        try:
            if test_func():
                print(f"  [OK] Passed")
                passed += 1
            else:
                print(f"  [FAIL] Failed")
                failed += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            failed += 1
    
    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print()
        print("Integration ready!")
        print("Run: python -m zeroai_tui.integration")
    
    return failed == 0


def test_import():
    """Test importing zeroai_tui"""
    import zeroai_tui
    return hasattr(zeroai_tui, '__version__')


def test_zai_chat():
    """Test importing zai_chat"""
    from zeroai_tui import zai_chat
    return hasattr(zai_chat, 'ZeroAIChat')


def test_integration_module():
    """Test importing integration"""
    from zeroai_tui import integration
    return hasattr(integration, 'ZeroAIIntegration')


def test_create_chat():
    """Test creating ZeroAIChat"""
    from zeroai_tui.zai_chat import ZeroAIChat
    chat = ZeroAIChat()
    return chat is not None


def test_create_message():
    """Test creating ChatMessage"""
    from zeroai_tui.zai_chat import ChatMessage
    msg = ChatMessage("user", "Hello")
    return msg.role == "user" and msg.content == "Hello"


def test_markdown():
    """Test markdown rendering"""
    from zeroai_tui import render_markdown
    lines = render_markdown("# Test\n**Bold**")
    return len(lines) > 0


def test_highlight():
    """Test code highlighting"""
    from zeroai_tui import highlight_code
    tokens = highlight_code("x = 1 + 2")
    return len(tokens) > 0


if __name__ == "__main__":
    success = test_integration()
    sys.exit(0 if success else 1)
