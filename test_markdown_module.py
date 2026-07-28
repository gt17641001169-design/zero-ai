"""Markdown 聚合模块测试"""
import sys
import os
sys.path.insert(0, r"d:\C\C")

from zeroai.tui.markdown import (
    render_markdown,
    _safe_markdown,
    render_latex_in_text,
    _latex_to_unicode,
    render_image_preview,
    _normalize_markdown_for_academic,
    is_loaded_from_tui_agent,
    get_module_info,
)

def test_module_info():
    info = get_module_info()
    print(f"[1] Module info: {info}")
    assert info["count"] == 6, f"Expected 6 exports, got {info['count']}"
    assert info["mode"] in ("wrapper", "standalone")
    return True

def test_latex_greek():
    result = _latex_to_unicode(r"\alpha + \beta = \gamma")
    print(f"[2] Greek letters: {result!r}")
    assert result == "α + β = γ", f"Got {result!r}"
    return True

def test_latex_super_sub():
    result = _latex_to_unicode(r"x_1^2 + y_{10}^{n+1}")
    print(f"[3] Super/subscripts: {result!r}")
    # 应该包含下标和上标
    assert "₁" in result and "²" in result, f"Got {result!r}"
    return True

def test_latex_frac():
    result = _latex_to_unicode(r"\frac{a}{b}")
    print(f"[4] Fraction: {result!r}")
    assert "a⁄b" == result or "a/b" == result, f"Got {result!r}"
    return True

def test_latex_sqrt():
    result = _latex_to_unicode(r"\sqrt{x}")
    print(f"[5] Square root: {result!r}")
    assert "√" in result, f"Got {result!r}"
    return True

def test_latex_matrix():
    result = _latex_to_unicode(r"\begin{pmatrix}a & b \\ c & d\end{pmatrix}")
    print(f"[6] Matrix: {result!r}")
    assert "a" in result and "d" in result, f"Got {result!r}"
    return True

def test_latex_in_text_inline():
    text = "The formula $E=mc^2$ is famous."
    result = render_latex_in_text(text)
    print(f"[7] Inline math: {result!r}")
    # E=mc^2 应该被转换为 E=mc²
    assert "E=mc²" in result, f"Got {result!r}"
    return True

def test_latex_in_text_block():
    text = "Block formula:\n$$\\sum_{i=1}^{n} x_i^2$$\nEnd."
    result = render_latex_in_text(text)
    print(f"[8] Block math: {result!r}")
    # 应该包含 Σ 和 ²
    assert "Σ" in result, f"Got {result!r}"
    return True

def test_normalize_markdown():
    text = "### Title\nContent"
    result = _normalize_markdown_for_academic(text)
    print(f"[9] Normalized markdown: {result!r}")
    assert "### Title" in result
    return True

def test_safe_markdown():
    result = _safe_markdown("# Hello")
    print(f"[10] Safe markdown type: {type(result).__name__}")
    # 应该返回 rich.markdown.Markdown 实例或字符串
    assert result is not None
    return True

def main():
    print("=" * 60)
    print("ZeroAI TUI Markdown Module Tests")
    print("=" * 60)
    print()

    tests = [
        test_module_info,
        test_latex_greek,
        test_latex_super_sub,
        test_latex_frac,
        test_latex_sqrt,
        test_latex_matrix,
        test_latex_in_text_inline,
        test_latex_in_text_block,
        test_normalize_markdown,
        test_safe_markdown,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
