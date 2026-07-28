"""
ZeroAI Full Integration Test
"""
import sys
import os

# Add paths
sys.path.insert(0, os.path.dirname(__file__))


def test_full_integration():
    """Test complete integration"""
    print("=" * 60)
    print("ZeroAI Full Integration Test")
    print("=" * 60)
    print()
    
    tests = [
        ("Import zeroai_tui", test_import_zeroai_tui),
        ("Import zeroai package", test_import_zeroai),
        ("Import tui_agent", test_import_tui_agent),
        ("Create integration", test_create_integration),
        ("Expert system ready", test_expert_system),
        ("LLM module ready", test_llm_module),
        ("Config module ready", test_config),
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
        print("Full integration ready!")
        print()
        print("Usage:")
        print("  # Run with Textual UI (default)")
        print("  python tui_agent.py")
        print()
        print("  # Run with zeroai-tui UI")
        print("  python tui_agent.py --ui zeroai-tui")
    
    return failed == 0


def test_import_zeroai_tui():
    """Test importing zeroai_tui"""
    import zeroai_tui
    return hasattr(zeroai_tui, '__version__')


def test_import_zeroai():
    """Test importing zeroai package"""
    import zeroai
    return hasattr(zeroai, '__version__')


def test_import_tui_agent():
    """Test importing tui_agent"""
    import tui_agent
    return hasattr(tui_agent, 'main')


def test_create_integration():
    """Test creating integration"""
    from zeroai_tui.integration import ZeroAIIntegration
    app = ZeroAIIntegration()
    return app is not None


def test_expert_system():
    """Test expert system"""
    from zeroai.core.expert import ExpertRouter
    router = ExpertRouter()
    return router is not None


def test_llm_module():
    """Test LLM module"""
    from zeroai.core import llm
    return hasattr(llm, 'LLMClient')


def test_config():
    """Test config module"""
    from zeroai.core.config import Config
    config = Config()
    return config is not None


if __name__ == "__main__":
    success = test_full_integration()
    sys.exit(0 if success else 1)
