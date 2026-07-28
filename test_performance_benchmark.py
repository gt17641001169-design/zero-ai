"""性能基准测试（阶段 H.3）

对比 Zig / C / Python 三层渲染路径的性能：
1. 纯 Python 渲染（baseline）
2. Zig 共享库渲染（如果可用）
3. C 扩展渲染（如果可用）

测试场景：
- 小缓冲区（20x5 = 100 cells）
- 中缓冲区（80x24 = 1920 cells）
- 大缓冲区（200x100 = 20000 cells）
- 压力测试（连续 100 次 diff）

运行方式：
    python test_performance_benchmark.py
"""
from __future__ import annotations

import os
import sys
import time
import statistics
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "zeroai-tui"))
sys.path.insert(0, os.path.dirname(__file__))

# 检测可用的渲染后端
HAS_ZIG_RENDERER = False
HAS_C_RENDERER = False
HAS_PURE_PYTHON = True

try:
    from zeroai_tui._zig_bindings import HAS_ZIG_RENDERER as _ZIG_OK
    HAS_ZIG_RENDERER = _ZIG_OK
except ImportError:
    pass

try:
    from zeroai_tui import _renderer
    HAS_C_RENDERER = True
except ImportError:
    pass


# ============================================================================
# 纯 Python 渲染实现（baseline）
# ============================================================================

def pure_python_diff(
    current_chars: List[List[str]],
    current_styles: List[List[Any]],
    next_chars: List[List[str]],
    next_styles: List[List[Any]],
    rows: int,
    cols: int,
) -> str:
    """纯 Python 实现的缓冲区 diff（简化版）"""
    output = []
    output.append("\033[0m")  # reset

    for row in range(rows):
        for col in range(cols):
            # 获取字符
            cur_ch = ""
            nxt_ch = ""
            if row < len(next_chars) and col < len(next_chars[row]):
                nxt_ch = next_chars[row][col] or " "
            if row < len(current_chars) and col < len(current_chars[row]):
                cur_ch = current_chars[row][col] or " "

            # 检查变化
            if nxt_ch != cur_ch:
                # 移动光标
                output.append(f"\033[{row + 1};{col + 1}H")
                # 写入字符
                output.append(nxt_ch)
            elif row < len(next_styles) and col < len(next_styles[row]):
                # 检查样式变化（简化）
                nxt_style = next_styles[row][col] if col < len(next_styles[row]) else None
                cur_style = current_styles[row][col] if row < len(current_styles) and col < len(current_styles[row]) else None
                if nxt_style != cur_style and nxt_style is not None:
                    output.append(f"\033[{row + 1};{col + 1}H")
                    output.append(nxt_ch)

    return "".join(output)


# ============================================================================
# 测试数据生成
# ============================================================================

def make_test_buffer(rows: int, cols: int, fill_ratio: float = 0.3) -> Tuple[Any, Any, Any, Any]:
    """生成测试缓冲区

    Args:
        rows: 行数
        cols: 列数
        fill_ratio: 变化单元格比例

    Returns:
        (current_chars, current_styles, next_chars, next_styles)
    """
    # 简单的字符样式（用 None 或 dict）
    current_chars = [[" "] * cols for _ in range(rows)]
    current_styles = [[None] * cols for _ in range(rows)]

    next_chars = [[" "] * cols for _ in range(rows)]
    next_styles = [[None] * cols for _ in range(rows)]

    # 填充 next 缓冲区
    import random
    random.seed(42)  # 可复现

    total_cells = rows * cols
    changes = int(total_cells * fill_ratio)

    for _ in range(changes):
        row = random.randint(0, rows - 1)
        col = random.randint(0, cols - 1)
        ch = chr(ord("A") + (col % 26))
        next_chars[row][col] = ch
        next_styles[row][col] = {"bold": True, "fg": "\033[31m"}

    return current_chars, current_styles, next_chars, next_styles


def make_render_buffer(rows: int, cols: int, fill_ratio: float = 0.3):
    """生成 zeroai_tui.RenderBuffer 测试数据"""
    try:
        from zeroai_tui.renderer import RenderBuffer, Style
        from zeroai_tui.terminal import Color
    except ImportError:
        return None, None

    current = RenderBuffer(cols, rows)
    next_buf = RenderBuffer(cols, rows)

    import random
    random.seed(42)

    total_cells = rows * cols
    changes = int(total_cells * fill_ratio)

    for _ in range(changes):
        row = random.randint(0, rows - 1)
        col = random.randint(0, cols - 1)
        ch = chr(ord("A") + (col % 26))
        next_buf.put(row, col, ch, Style(bold=True, fg=Color.RED))

    return current, next_buf


# ============================================================================
# 基准测试
# ============================================================================

def benchmark_pure_python(
    rows: int,
    cols: int,
    iterations: int = 100,
) -> Dict[str, Any]:
    """纯 Python 渲染基准"""
    cur_ch, cur_st, nxt_ch, nxt_st = make_test_buffer(rows, cols)

    durations = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = pure_python_diff(cur_ch, cur_st, nxt_ch, nxt_st, rows, cols)
        elapsed = time.perf_counter() - start
        durations.append(elapsed)

    return {
        "backend": "pure_python",
        "rows": rows,
        "cols": cols,
        "cells": rows * cols,
        "iterations": iterations,
        "total_time": sum(durations),
        "avg_time": statistics.mean(durations),
        "min_time": min(durations),
        "max_time": max(durations),
        "median_time": statistics.median(durations),
        "std_dev": statistics.stdev(durations) if len(durations) > 1 else 0,
        "ops_per_sec": iterations / sum(durations) if sum(durations) > 0 else 0,
        "output_size": len(result),
    }


def benchmark_zig(
    rows: int,
    cols: int,
    iterations: int = 100,
) -> Optional[Dict[str, Any]]:
    """Zig 渲染基准"""
    if not HAS_ZIG_RENDERER:
        return None

    try:
        from zeroai_tui._zig_bindings import diff_buffers as zig_diff
    except ImportError:
        return None

    cur_ch, cur_st, nxt_ch, nxt_st = make_test_buffer(rows, cols)

    durations = []
    output_size = 0
    for _ in range(iterations):
        start = time.perf_counter()
        result = zig_diff(cur_ch, cur_st, nxt_ch, nxt_st, rows, cols)
        elapsed = time.perf_counter() - start
        durations.append(elapsed)
        if result:
            output_size = len(result)

    return {
        "backend": "zig",
        "rows": rows,
        "cols": cols,
        "cells": rows * cols,
        "iterations": iterations,
        "total_time": sum(durations),
        "avg_time": statistics.mean(durations),
        "min_time": min(durations),
        "max_time": max(durations),
        "median_time": statistics.median(durations),
        "std_dev": statistics.stdev(durations) if len(durations) > 1 else 0,
        "ops_per_sec": iterations / sum(durations) if sum(durations) > 0 else 0,
        "output_size": output_size,
    }


def benchmark_c(
    rows: int,
    cols: int,
    iterations: int = 100,
) -> Optional[Dict[str, Any]]:
    """C 扩展渲染基准"""
    if not HAS_C_RENDERER:
        return None

    try:
        from zeroai_tui import _renderer
        from zeroai_tui.renderer import RenderBuffer, Style
        from zeroai_tui.terminal import Color
    except ImportError:
        return None

    durations = []
    output_size = 0

    for _ in range(iterations):
        current = RenderBuffer(cols, rows)
        next_buf = RenderBuffer(cols, rows)

        # 填充
        import random
        random.seed(42)
        for _ in range(int(rows * cols * 0.3)):
            row = random.randint(0, rows - 1)
            col = random.randint(0, cols - 1)
            ch = chr(ord("A") + (col % 26))
            next_buf.put(row, col, ch, Style(bold=True, fg=Color.RED))

        start = time.perf_counter()
        result = _renderer.diff_buffers(
            current.buffer, current.styles,
            next_buf.buffer, next_buf.styles,
            rows, cols,
        )
        elapsed = time.perf_counter() - start
        durations.append(elapsed)
        if result:
            output_size = len(result)

    return {
        "backend": "c_extension",
        "rows": rows,
        "cols": cols,
        "cells": rows * cols,
        "iterations": iterations,
        "total_time": sum(durations),
        "avg_time": statistics.mean(durations),
        "min_time": min(durations),
        "max_time": max(durations),
        "median_time": statistics.median(durations),
        "std_dev": statistics.stdev(durations) if len(durations) > 1 else 0,
        "ops_per_sec": iterations / sum(durations) if sum(durations) > 0 else 0,
        "output_size": output_size,
    }


def run_benchmark_suite() -> Dict[str, Any]:
    """运行完整基准测试套件

    Returns:
        {
            "backends": {"pure_python": bool, "zig": bool, "c": bool},
            "results": [...],
            "comparisons": [...],
        }
    """
    print("=" * 70)
    print("ZeroAI TUI 渲染性能基准测试")
    print("=" * 70)
    print()

    # 检测后端
    backends = {
        "pure_python": True,
        "zig": HAS_ZIG_RENDERER,
        "c": HAS_C_RENDERER,
    }

    print("可用后端:")
    for name, available in backends.items():
        status = "[可用]" if available else "[不可用]"
        print(f"  {name:15s} {status}")
    print()

    # 测试场景
    scenarios = [
        ("小缓冲区", 5, 20, 100),
        ("中缓冲区", 24, 80, 100),
        ("大缓冲区", 100, 200, 50),
        ("压力测试", 24, 80, 500),
    ]

    all_results: List[Dict[str, Any]] = []

    for name, rows, cols, iters in scenarios:
        print(f"\n{'=' * 70}")
        print(f"场景: {name} ({rows}x{cols} = {rows*cols} cells, {iters} 次)")
        print(f"{'=' * 70}")

        # 纯 Python
        print(f"\n  [纯 Python] 运行中...", end="", flush=True)
        py_result = benchmark_pure_python(rows, cols, iters)
        all_results.append(py_result)
        print(f" 完成: {py_result['avg_time']*1000:.2f}ms/op, {py_result['ops_per_sec']:.1f} ops/s")

        # Zig
        if HAS_ZIG_RENDERER:
            print(f"  [Zig]        运行中...", end="", flush=True)
            zig_result = benchmark_zig(rows, cols, iters)
            if zig_result:
                all_results.append(zig_result)
                print(f" 完成: {zig_result['avg_time']*1000:.2f}ms/op, {zig_result['ops_per_sec']:.1f} ops/s")
        else:
            print(f"  [Zig]        跳过（不可用）")

        # C
        if HAS_C_RENDERER:
            print(f"  [C 扩展]     运行中...", end="", flush=True)
            c_result = benchmark_c(rows, cols, iters)
            if c_result:
                all_results.append(c_result)
                print(f" 完成: {c_result['avg_time']*1000:.2f}ms/op, {c_result['ops_per_sec']:.1f} ops/s")
        else:
            print(f"  [C 扩展]     跳过（不可用）")

    # 对比分析
    print(f"\n{'=' * 70}")
    print("性能对比分析")
    print(f"{'=' * 70}")

    comparisons = []
    for name, rows, cols, _ in scenarios:
        py = next((r for r in all_results if r["backend"] == "pure_python" and r["rows"] == rows and r["cols"] == cols), None)
        zig = next((r for r in all_results if r["backend"] == "zig" and r["rows"] == rows and r["cols"] == cols), None)
        c = next((r for r in all_results if r["backend"] == "c_extension" and r["rows"] == rows and r["cols"] == cols), None)

        print(f"\n  {name} ({rows}x{cols}):")
        if py:
            print(f"    纯 Python:  {py['avg_time']*1000:8.2f} ms/op  {py['ops_per_sec']:8.1f} ops/s")
        if zig:
            speedup = py['avg_time'] / zig['avg_time'] if py and py['avg_time'] > 0 else 0
            print(f"    Zig:        {zig['avg_time']*1000:8.2f} ms/op  {zig['ops_per_sec']:8.1f} ops/s  (加速 {speedup:.2f}x)")
            comparisons.append({
                "scenario": name,
                "rows": rows,
                "cols": cols,
                "python_avg_ms": py['avg_time'] * 1000 if py else 0,
                "zig_avg_ms": zig['avg_time'] * 1000,
                "speedup": speedup,
            })
        if c:
            speedup = py['avg_time'] / c['avg_time'] if py and py['avg_time'] > 0 else 0
            print(f"    C 扩展:     {c['avg_time']*1000:8.2f} ms/op  {c['ops_per_sec']:8.1f} ops/s  (加速 {speedup:.2f}x)")
            comparisons.append({
                "scenario": name,
                "rows": rows,
                "cols": cols,
                "python_avg_ms": py['avg_time'] * 1000 if py else 0,
                "c_avg_ms": c['avg_time'] * 1000,
                "speedup": speedup,
            })

    return {
        "backends": backends,
        "results": all_results,
        "comparisons": comparisons,
    }


def main():
    """主入口"""
    results = run_benchmark_suite()

    # 保存结果
    import json
    output_file = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n结果已保存到: {output_file}")
    except Exception as e:
        print(f"\n保存结果失败: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
