"""
Performance test: Python vs C rendering
"""
import sys
import os
import time

# Add paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from zeroai_tui.renderer import Renderer, RenderBuffer, Style, HAS_C_RENDERER
from zeroai_tui.terminal import Color


def test_rendering_performance():
    """Test rendering performance"""
    print("=" * 60)
    print("ZeroAI TUI Rendering Performance Test")
    print("=" * 60)
    print()
    
    print(f"C Extension available: {HAS_C_RENDERER}")
    print()
    
    # Test parameters
    rows = 24
    cols = 80
    iterations = 100
    
    # Create renderer
    renderer = Renderer()
    renderer.cols = cols
    renderer.rows = rows
    renderer.current_buffer = RenderBuffer(cols, rows)
    renderer.next_buffer = RenderBuffer(cols, rows)
    
    # Fill with test data
    test_data = [
        ("Hello World", Style(bold=True, fg=Color.CYAN)),
        ("Test Line", Style(fg=Color.GREEN)),
        ("Error Message", Style(bold=True, fg=Color.RED)),
        ("Normal Text", Style()),
        ("Dim Text", Style(dim=True, fg=Color.WHITE)),
    ]
    
    # Test 1: Fill buffer
    print("[Test 1] Fill buffer...")
    start = time.perf_counter()
    
    for _ in range(iterations):
        renderer.clear()
        for row in range(min(rows, 10)):
            text, style = test_data[row % len(test_data)]
            renderer.write(row, 0, text, style)
        
        # Simulate flush (without actual terminal output)
        if HAS_C_RENDERER:
            try:
                from zeroai_tui import _renderer
                _renderer.diff_buffers(
                    renderer.current_buffer.buffer,
                    renderer.current_buffer.styles,
                    renderer.next_buffer.buffer,
                    renderer.next_buffer.styles,
                    rows,
                    cols
                )
            except:
                pass
        
        # Swap buffers
        renderer.current_buffer, renderer.next_buffer = renderer.next_buffer, renderer.current_buffer
    
    elapsed = time.perf_counter() - start
    print(f"  Time: {elapsed:.3f}s ({iterations/elapsed:.1f} iterations/sec)")
    print()
    
    # Test 2: Diff buffers
    print("[Test 2] Buffer diff...")
    
    # Create different buffers
    renderer.clear()
    for row in range(5):
        renderer.write(row, 0, f"Changed line {row}", Style(fg=Color.YELLOW))
    
    # Copy to current
    import copy
    current = copy.deepcopy(renderer.next_buffer)
    
    # Make changes in next
    renderer.clear()
    for row in range(5):
        renderer.write(row, 0, f"New line {row}", Style(fg=Color.GREEN))
    
    start = time.perf_counter()
    
    for _ in range(iterations):
        if HAS_C_RENDERER:
            try:
                from zeroai_tui import _renderer
                _renderer.diff_buffers(
                    current.buffer,
                    current.styles,
                    renderer.next_buffer.buffer,
                    renderer.next_buffer.styles,
                    rows,
                    cols
                )
            except:
                # Python fallback
                pass
        else:
            # Python implementation
            output = []
            for r in range(rows):
                for c in range(cols):
                    if (current.buffer[r][c] != renderer.next_buffer.buffer[r][c] or
                        current.styles[r][c] != renderer.next_buffer.styles[r][c]):
                        output.append(f"\033[{r+1};{c+1}H")
                        output.append(renderer.next_buffer.buffer[r][c])
            "".join(output)
    
    elapsed = time.perf_counter() - start
    print(f"  Time: {elapsed:.3f}s ({iterations/elapsed:.1f} iterations/sec)")
    print()
    
    # Test 3: Style generation
    print("[Test 3] Style generation...")
    
    styles = [
        Style(bold=True, fg=Color.RED),
        Style(dim=True, fg=Color.GREEN),
        Style(italic=True, fg=Color.BLUE),
        Style(bold=True, italic=True, underline=True, fg=Color.YELLOW, bg=Color.BLACK),
    ]
    
    start = time.perf_counter()
    
    for _ in range(iterations * 100):
        for style in styles:
            if HAS_C_RENDERER:
                try:
                    from zeroai_tui import _renderer
                    _renderer.make_style(
                        style.bold,
                        style.dim,
                        style.italic,
                        style.underline,
                        style.fg or "",
                        style.bg or ""
                    )
                except:
                    pass
            else:
                # Python fallback
                codes = []
                if style.bold:
                    codes.append(Color.BOLD)
                if style.dim:
                    codes.append(Color.DIM)
                if style.italic:
                    codes.append(Color.ITALIC)
                if style.underline:
                    codes.append(Color.UNDERLINE)
                if style.fg:
                    codes.append(style.fg)
                if style.bg:
                    codes.append(style.bg)
                "".join(codes)
    
    elapsed = time.perf_counter() - start
    print(f"  Time: {elapsed:.3f}s")
    print()
    
    print("=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    test_rendering_performance()
