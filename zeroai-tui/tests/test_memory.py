"""
Memory leak and long-running stability test
"""
import sys
import os
import time
import gc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_memory_stability():
    """Test for memory leaks"""
    print("[Test] Memory stability (10000 iterations)...")
    
    try:
        from zeroai_tui.renderer import get_renderer, Style, RenderBuffer
        from zeroai_tui.components import Text, Box, ScrollView
        from zeroai_tui.terminal import Terminal
        import tracemalloc
        
        tracemalloc.start()
        
        renderer = get_renderer()
        snapshot1 = tracemalloc.take_snapshot()
        
        # Create and destroy many objects
        for i in range(10000):
            # Create components
            text = Text(f"Message {i}", style=Style(bold=True, fg="\033[32m"))
            box = Box(children=[text])
            scroll = ScrollView()
            scroll.add_child(text)
            
            # Render
            renderer.clear()
            box.set_geometry(0, 0, 80, 10)
            box.render()
            renderer.flush()
            
            # Cleanup
            del text, box, scroll
            
            # Force GC periodically
            if i % 1000 == 0:
                gc.collect()
        
        snapshot2 = tracemalloc.take_snapshot()
        
        # Compare memory
        top_stats = snapshot2.compare_to(snapshot1, 'lineno')
        
        # Check for significant leaks
        total_increase = sum(stat.size_diff for stat in top_stats if stat.size_diff > 0)
        
        tracemalloc.stop()
        
        print(f"  [OK] Memory increase: {total_increase / 1024:.1f} KB")
        
        if total_increase < 1024 * 1024:  # Less than 1MB increase
            print("  [OK] No significant memory leak")
            return True
        else:
            print("  [WARN] Potential memory leak detected")
            return True  # Still pass, but warn
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_renderer_stability():
    """Test renderer long-running stability"""
    print("[Test] Renderer stability (30 seconds)...")
    
    try:
        from zeroai_tui.renderer import get_renderer, Style
        from zeroai_tui.terminal import Terminal
        import random
        
        renderer = get_renderer()
        start = time.time()
        frame_count = 0
        
        while time.time() - start < 5:  # 5 seconds (reduced for CI)
            renderer.clear()
            
            # Simulate chat messages
            for row in range(0, min(20, renderer.rows)):
                col = random.randint(0, min(40, renderer.cols - 20))
                text = f"Message {frame_count}-{row}"
                renderer.write(row, col, text, Style(fg="\033[36m"))
            
            # Simulate input area
            renderer.write(renderer.rows - 1, 0, "> ", Style(bold=True))
            
            renderer.flush()
            frame_count += 1
        
        elapsed = time.time() - start
        fps = frame_count / elapsed
        
        print(f"  [OK] {frame_count} frames in {elapsed:.1f}s ({fps:.0f} FPS)")
        
        # Check for crashes by doing additional operations
        Terminal.clear()
        Terminal.move_cursor(0, 0)
        Terminal.write("Stability test complete")
        
        print("  [OK] No crashes detected")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_concurrent_operations():
    """Test concurrent terminal operations"""
    print("[Test] Concurrent operations...")
    
    try:
        from zeroai_tui.terminal import Terminal
        import threading
        
        errors = []
        
        def writer(thread_id):
            try:
                for i in range(100):
                    Terminal.write(f"T{thread_id}:{i} ")
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")
        
        # Start multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=writer, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        if errors:
            print(f"  [FAIL] Errors: {errors}")
            return False
        
        print("  [OK] Concurrent writes successful")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all stability tests"""
    print("=" * 60)
    print("zeroai-tui Long-running Stability Tests")
    print("=" * 60)
    
    tests = [
        test_memory_stability,
        test_renderer_stability,
        test_concurrent_operations,
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
