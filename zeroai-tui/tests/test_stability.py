"""
zeroai-tui stability tests
"""
import sys
import os
import time
import traceback

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_terminal_basic():
    """Test basic terminal operations"""
    print("[Test] Terminal basic operations...")
    
    try:
        from zeroai_tui.terminal import Terminal
        
        # Test get_size
        cols, rows = Terminal.get_size()
        assert cols > 0 and rows > 0, f"Invalid size: {cols}x{rows}"
        print(f"  [OK] Terminal size: {cols}x{rows}")
        
        # Test write
        Terminal.write("test")
        print("  [OK] Terminal write")
        
        # Test clear
        Terminal.clear()
        print("  [OK] Terminal clear")
        
        # Test cursor
        Terminal.move_cursor(0, 0)
        Terminal.set_cursor_visible(False)
        Terminal.set_cursor_visible(True)
        print("  [OK] Cursor operations")
        
        # Test color support
        color = Terminal.supports_color()
        print(f"  [OK] Color support: {color}")
        
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        traceback.print_exc()
        return False


def test_terminal_raw_mode():
    """Test raw mode toggle"""
    print("[Test] Terminal raw mode...")
    
    try:
        from zeroai_tui.terminal import Terminal
        
        # Enable raw mode
        Terminal.set_raw_mode(True)
        print("  [OK] Raw mode enabled")
        
        # Read a char (with timeout simulation)
        start = time.time()
        while time.time() - start < 0.1:
            char = Terminal.read_char()
            if char:
                print(f"  [OK] Read char: {repr(char)}")
                break
        
        # Disable raw mode
        Terminal.set_raw_mode(False)
        print("  [OK] Raw mode disabled")
        
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        traceback.print_exc()
        return False


def test_renderer():
    """Test renderer operations"""
    print("[Test] Renderer...")
    
    try:
        from zeroai_tui.renderer import get_renderer, Style, RenderBuffer
        
        # Get renderer
        renderer = get_renderer()
        print(f"  [OK] Renderer initialized: {renderer.cols}x{renderer.rows}")
        
        # Test buffer operations
        buffer = RenderBuffer(80, 24)
        buffer.put(0, 0, 'A')
        buffer.write(1, 0, "Hello World")
        buffer.clear()
        print("  [OK] Buffer operations")
        
        # Test render
        output = buffer.render()
        assert isinstance(output, str)
        print(f"  [OK] Buffer render: {len(output)} chars")
        
        # Test renderer write
        renderer.clear()
        renderer.write(0, 0, "Test", Style(bold=True))
        renderer.flush()
        print("  [OK] Renderer write/flush")
        
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        traceback.print_exc()
        return False


def test_components():
    """Test component system"""
    print("[Test] Components...")
    
    try:
        from zeroai_tui.components import Text, Box, Input, ScrollView
        from zeroai_tui.renderer import Style
        
        # Test Text
        text = Text("Hello", style=Style(bold=True))
        assert text.text == "Hello"
        print("  [OK] Text component")
        
        # Test Box
        box = Box(children=[text])
        assert len(box.children) == 1
        print("  [OK] Box component")
        
        # Test Input
        input_field = Input(placeholder="> ")
        assert input_field.value == ""
        print("  [OK] Input component")
        
        # Test ScrollView
        scroll = ScrollView()
        for i in range(10):
            scroll.add_child(Text(f"Line {i}"))
        assert len(scroll.children) == 10
        print("  [OK] ScrollView component")
        
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        traceback.print_exc()
        return False


def test_input_handling():
    """Test input handling"""
    print("[Test] Input handling...")
    
    try:
        from zeroai_tui.components import Input, Event

        input_field = Input()
        input_field.set_focus(True)

        # Test typing
        input_field.handle_event(Event(Event.TYPE_KEY, data='H'))
        input_field.handle_event(Event(Event.TYPE_KEY, data='i'))
        assert input_field.value == "Hi"
        print("  [OK] Character input")

        # Test backspace
        input_field.handle_event(Event(Event.TYPE_KEY, data='\x7f'))
        assert input_field.value == "H"
        print("  [OK] Backspace")

        # Test cursor movement
        assert input_field.cursor_pos == 1
        print("  [OK] Cursor position")

        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        traceback.print_exc()
        return False


def test_stress():
    """Stress test renderer"""
    print("[Test] Stress test...")
    
    try:
        from zeroai_tui.renderer import get_renderer, Style
        from zeroai_tui.terminal import Terminal
        import random
        
        renderer = get_renderer()
        
        start = time.time()
        iterations = 1000
        
        for i in range(iterations):
            renderer.clear()
            
            # Write random content
            for row in range(min(24, renderer.rows)):
                for col in range(min(80, renderer.cols)):
                    char = chr(random.randint(32, 126))
                    style = Style(bold=random.choice([True, False]))
                    renderer.put(row, col, char, style)
            
            renderer.flush()
        
        elapsed = time.time() - start
        fps = iterations / elapsed
        
        print(f"  [OK] {iterations} frames in {elapsed:.2f}s ({fps:.0f} FPS)")
        
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        traceback.print_exc()
        return False


def main():
    """Run all stability tests"""
    print("=" * 60)
    print("zeroai-tui Stability Tests")
    print("=" * 60)
    
    tests = [
        test_terminal_basic,
        test_terminal_raw_mode,
        test_renderer,
        test_components,
        test_input_handling,
        test_stress,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        print()
        if test():
            passed += 1
        else:
            failed += 1
    
    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
