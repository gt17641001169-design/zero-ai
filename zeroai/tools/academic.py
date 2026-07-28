"""学术研究工具

迁移来源：tui_agent.py 行 3998-4088（LaTeX 常量）、4091-4389（_latex_to_unicode）、
4392-4973（学术搜索/引用校验/文献综述/公式渲染）

提供以下纯函数：
- _latex_to_unicode：将 LaTeX 公式转换为 Unicode 终端可显示文本
- academic_search：学术文献搜索（Semantic Scholar API）
- arxiv_search：arXiv 预印本论文搜索
- citation_check：校验文献引用真实性
- _format_citation_result：格式化引用校验结果
- literature_review：多文献综合对比分析
- _lit_review_search_ss：Semantic Scholar 检索辅助
- _lit_review_search_arxiv：arXiv 检索辅助
- render_formula：渲染 LaTeX 公式

依赖：
- 标准库：re, json, urllib, difflib
- .network.web_fetch（可选，本模块实际直接使用 urllib.request 以获得更细粒度控制）
- zeroai.core.response_utils._jaccard_similarity（可选，本模块实际使用 difflib.SequenceMatcher 做标题相似度）

注意：本模块的学术检索函数直接使用 urllib.request 调用 Semantic Scholar / arXiv API，
未通过 web_fetch 中转，以保证对 API 响应格式（JSON/XML）的精确控制。
"""
import re
import json
import urllib.request
import urllib.parse
import urllib.error


# ====== LaTeX 符号映射表 ======
# 迁移来源：tui_agent.py 行 3998-4088

# 希腊字母
_LATEX_GREEK = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ", r"\vartheta": "ϑ", r"\iota": "ι", r"\kappa": "κ",
    r"\lambda": "λ", r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ",
    r"\pi": "π", r"\varpi": "ϖ", r"\rho": "ρ", r"\varrho": "ϱ",
    r"\sigma": "σ", r"\varsigma": "ς", r"\tau": "τ", r"\upsilon": "υ",
    r"\phi": "φ", r"\varphi": "φ", r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω",
    r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ",
    r"\Xi": "Ξ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Upsilon": "Υ",
    r"\Phi": "Φ", r"\Psi": "Ψ", r"\Omega": "Ω",
}

# 数学运算符与符号
_LATEX_OPERATORS = {
    r"\times": "×", r"\div": "÷", r"\pm": "±", r"\mp": "∓",
    r"\cdot": "·", r"\cdots": "⋯", r"\ldots": "…", r"\vdots": "⋮", r"\ddots": "⋱",
    r"\infty": "∞", r"\partial": "∂", r"\nabla": "∇", r"\forall": "∀", r"\exists": "∃",
    r"\neg": "¬", r"\land": "∧", r"\lor": "∨", r"\oplus": "⊕", r"\ominus": "⊖",
    r"\otimes": "⊗", r"\odot": "⊙", r"\cap": "∩", r"\cup": "∪", r"\setminus": "∖",
    r"\subset": "⊂", r"\supset": "⊃", r"\subseteq": "⊆", r"\supseteq": "⊇",
    r"\in": "∈", r"\notin": "∉", r"\ni": "∋",
    r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈", r"\equiv": "≡",
    r"\sim": "∼", r"\simeq": "≃", r"\cong": "≅", r"\propto": "∝",
    r"\to": "→", r"\rightarrow": "→", r"\leftarrow": "←", r"\gets": "←",
    r"\Rightarrow": "⇒", r"\Leftarrow": "⇐", r"\Leftrightarrow": "⇔", r"\iff": "⟺",
    r"\mapsto": "↦", r"\uparrow": "↑", r"\downarrow": "↓", r"\updownarrow": "↕",
    r"\sum": "Σ", r"\prod": "∏", r"\coprod": "∐", r"\int": "∫", r"\oint": "∮",
    r"\bigcup": "⋃", r"\bigcap": "⋂", r"\bigoplus": "⨁", r"\bigotimes": "⨂",
    r"\sqrt": "√", r"\cubert": "∛", r"\fourthroot": "∜",
    r"\angle": "∠", r"\perp": "⊥", r"\parallel": "∥", r"\triangle": "△",
    r"\circ": "∘", r"\bullet": "•", r"\star": "⋆", r"\dagger": "†", r"\ddagger": "‡",
    r"\aleph": "ℵ", r"\beth": "ℶ", r"\hbar": "ℏ", r"\ell": "ℓ",
    r"\Re": "ℜ", r"\Im": "ℑ", r"\wp": "℘", r"\mho": "℧",
    r"\angle": "∠", r"\measuredangle": "∡", r"\sphericalangle": "∢",
    r"\prime": "′", r"\backprime": "‵",
    r"\colon": ":", r"\vert": "|", r"\Vert": "‖", r"\backslash": "\\",
    r"\degree": "°", r"\circ": "∘",
    r"\leqq": "≦", r"\geqq": "≧", r"\lessgtr": "≶", r"\gtrless": "≷",
    r"\prec": "≺", r"\succ": "≻", r"\preceq": "≼", r"\succeq": "≽",
    r"\emptyset": "∅", r"\varnothing": "∅",
    r"\mathbb{R}": "ℝ", r"\mathbb{Z}": "ℤ", r"\mathbb{Q}": "ℚ",
    r"\mathbb{N}": "ℕ", r"\mathbb{C}": "ℂ", r"\mathbb{H}": "ℍ",
    r"\mathbb{A}": "𝔸", r"\mathbb{B}": "𝔹", r"\mathbb{D}": "𝔻",
    r"\mathbb{E}": "𝔼", r"\mathbb{F}": "𝔽", r"\mathbb{G}": "𝔾",
    r"\mathbb{I}": "𝕀", r"\mathbb{J}": "𝕁", r"\mathbb{K}": "𝕂",
    r"\mathbb{L}": "𝕃", r"\mathbb{M}": "𝕄", r"\mathbb{O}": "𝕆",
    r"\mathbb{P}": "ℙ", r"\mathbb{S}": "𝕊", r"\mathbb{T}": "𝕋",
    r"\mathbb{U}": "𝕌", r"\mathbb{V}": "𝕍", r"\mathbb{W}": "𝕎", r"\mathbb{X}": "𝕏",
    r"\mathbb{Y}": "𝕐",
}

# 下标映射（Unicode 下标字符）
_LATEX_SUBSCRIPT = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "o": "ₒ", "x": "ₓ", "h": "ₕ",
    "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "p": "ₚ",
    "s": "ₛ", "t": "ₜ", "i": "ᵢ", "j": "ⱼ", "u": "ᵤ", "v": "ᵥ",
}

# 上标映射（Unicode 上标字符）
_LATEX_SUPERSCRIPT = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ",
    "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "i": "ⁱ", "j": "ʲ",
    "k": "ᵏ", "l": "ˡ", "m": "ᵐ", "n": "ⁿ", "o": "ᵒ",
    "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ",
    "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ",
    "A": "ᴬ", "B": "ᴮ", "D": "ᴰ", "E": "ᴱ", "G": "ᴳ",
    "H": "ᴴ", "I": "ᴵ", "J": "ᴶ", "K": "ᴷ", "L": "ᴸ",
    "M": "ᴹ", "N": "ᴺ", "O": "ᴼ", "P": "ᴾ", "R": "ᴿ",
    "T": "ᵀ", "U": "ᵁ", "V": "ⱽ", "W": "ᵂ",
    "α": "ᵅ", "β": "ᵝ", "γ": "ᵞ", "δ": "ᵟ", "ε": "ᵋ",
    "θ": "ᶿ", "ι": "ᶥ", "φ": "ᵠ", "χ": "ᵡ", "ψ": "ᵧ",
    "n": "ⁿ", "-": "⁻",
}

# 函数名映射（保持原样，不转换）
_LATEX_FUNCTIONS = {
    r"\sin", r"\cos", r"\tan", r"\cot", r"\sec", r"\csc",
    r"\arcsin", r"\arccos", r"\arctan",
    r"\sinh", r"\cosh", r"\tanh", r"\coth",
    r"\log", r"\ln", r"\lg", r"\exp",
    r"\lim", r"\max", r"\min", r"\sup", r"\inf",
    r"\arg", r"\det", r"\dim", r"\gcd", r"\hom", r"\ker", r"\deg",
    r"\operatorname",
}


def _latex_to_unicode(latex: str) -> str:
    r"""将单个 LaTeX 公式转换为 Unicode 终端可显示文本

    支持：
    - 希腊字母：\\alpha → α, \\Sigma → Σ
    - 运算符：\\times → ×, \\sum → Σ, \\int → ∫
    - 上下标：x_1 → x₁, x^2 → x², x_{10} → x₁₀, x^{n+1} → xⁿ⁺¹
    - 分数：\\frac{a}{b} → a⁄b（使用 Unicode 分数斜杠 ⁄ U+2044，比普通 / 更贴近真分数排版）
    - 根号：\\sqrt{x} → √x, \\sqrt[3]{x} → ∛x
    - 求和/积分上下限：\\sum_{i=1}^{n} → Σᵢ₌₁ⁿ
    - 黑板粗体：\\mathbb{R} → ℝ
    - 函数名：\\sin \\cos \\log 等保持原样

    迁移来源：tui_agent.py 行 4091-4389
    """
    s = latex.strip()
    # 去除首尾 $ 符号（已在调用前处理）
    s = s.strip("$")

    # 0. 预处理：\dfrac \tfrac \cfrac 统一当作 \frac 处理
    s = re.sub(r"\\[dtc]frac\b", r"\\frac", s)

    # 0.1 处理 \left( \right) \left[ \right] \left\{ \right\} 等自适应定界符
    s = s.replace(r"\left(", "(").replace(r"\right)", ")")
    s = s.replace(r"\left[", "[").replace(r"\right]", "]")
    s = s.replace(r"\left\{", "{").replace(r"\right\}", "}")
    s = s.replace(r"\left|", "|").replace(r"\right|", "|")
    s = s.replace(r"\left\|", "‖").replace(r"\right\|", "‖")
    s = s.replace(r"\left.", "").replace(r"\right.", "")

    # 0.2 处理 \big \Big \bigg \Bigg 等尺寸前缀（直接去除，保留定界符本身）
    # 关键：必须用 \b 保护 \bigcup \bigcap \bigoplus \bigotimes 等以 big 开头的命令不被误删
    s = re.sub(r"\\[bB]ig[lmr]?(?![a-zA-Z])\s*", "", s)
    s = re.sub(r"\\big[lmr]?(?![a-zA-Z])\s*", "", s)

    # 0.3 处理装饰符号（矢量、帽子、横线、波浪号、点导数）
    # 按命令长度降序处理，避免 \dot 匹配 \ddot 的前缀
    _DECO_MAP = [
        (r"\\overline",  "̄"),   # 上划线（组合符 U+0304）
        (r"\\underline", "̱"),   # 下划线（组合符 U+0332）
        (r"\\widehat",   "^"),   # 宽帽子
        (r"\\widetilde", "~"),   # 宽波浪
        (r"\\mathring",  "̊"),   # 圈（组合符 U+030A）
        (r"\\ddot",      "̈"),   # 二阶导数双点（组合符 U+0308）
        (r"\\dot",       "̇"),   # 一阶导数点（组合符 U+0307）
        (r"\\vec",       "→"),   # 矢量箭头（前置）
        (r"\\hat",       "^"),   # 帽子
        (r"\\bar",       "̄"),   # 上横线
        (r"\\tilde",     "~"),   # 波浪号
    ]
    for cmd_pat, deco_sym in _DECO_MAP:
        def _deco_repl(m, ds=deco_sym):
            body_u = _latex_to_unicode(m.group(1))
            if ds == "→":
                return f"→{body_u}"  # 矢量箭头前置
            return f"{body_u}{ds}"   # 组合符号后置
        s = re.sub(cmd_pat + r"\{([^{}]*)\}", _deco_repl, s)

    # 0.4 处理矩阵 \begin{matrix}...\end{matrix} 等
    # 使用 Unicode 矩阵专用括号 ⎡⎢⎣⎤⎥⎦（U+23A1-23A6），比普通 () 更清晰
    def _matrix_repl(m):
        env = m.group(1)
        body = m.group(2)
        # 按 \\ 分行，按 & 分列
        rows = [r.strip() for r in body.split(r"\\") if r.strip()]
        rendered_rows = []
        for row in rows:
            cells = [c.strip() for c in row.split("&")]
            rendered_cells = [_latex_to_unicode(c) for c in cells]
            rendered_rows.append("  ".join(rendered_cells))
        # 单行矩阵：用紧凑形式
        if len(rendered_rows) == 1:
            inner = rendered_rows[0]
            if env == "pmatrix":
                return f"( {inner} )"
            if env == "bmatrix":
                return f"[ {inner} ]"
            if env == "Bmatrix":
                return f"{{ {inner} }}"
            if env == "vmatrix":
                return f"| {inner} |"
            if env == "Vmatrix":
                return f"‖ {inner} ‖"
            return inner
        # 多行矩阵：用矩阵专用括号 ⎡⎢⎣ ⎤⎥⎦
        n = len(rendered_rows)
        # 左括号：第一行⎡，中间行⎢，最后一行⎣
        # 右括号：第一行⎤，中间行⎥，最后一行⎦
        left_brackets = {"pmatrix": ("⎡", "⎢", "⎣"),
                         "bmatrix": ("⎡", "⎢", "⎣"),
                         "Bmatrix": ("⎧", "⎨", "⎩"),
                         "vmatrix": ("⎢", "⎢", "⎢"),
                         "Vmatrix": ("⎢", "⎢", "⎢")}
        right_brackets = {"pmatrix": ("⎤", "⎥", "⎦"),
                          "bmatrix": ("⎤", "⎥", "⎦"),
                          "Bmatrix": ("⎫", "⎬", "⎭"),
                          "vmatrix": ("⎥", "⎥", "⎥"),
                          "Vmatrix": ("⎥", "⎥", "⎥")}
        lb = left_brackets.get(env, ("", "", ""))
        rb = right_brackets.get(env, ("", "", ""))
        lines = []
        for i, row in enumerate(rendered_rows):
            if n == 1:
                l, r = lb[0], rb[0]
            elif i == 0:
                l, r = lb[0], rb[0]
            elif i == n - 1:
                l, r = lb[2], rb[2]
            else:
                l, r = lb[1], rb[1]
            lines.append(f"{l}{row}{r}")
        return "\n".join(lines)
    s = re.sub(r"\\begin\{(matrix|pmatrix|bmatrix|Bmatrix|vmatrix|Vmatrix|smallmatrix)\}(.*?)\\end\{\1\}",
               _matrix_repl, s, flags=re.DOTALL)

    # 0.5 处理 cases 环境（分段函数）
    def _cases_repl(m):
        body = m.group(1)
        rows = [r.strip() for r in body.split(r"\\") if r.strip()]
        rendered = []
        for row in rows:
            parts = row.split("&")
            if len(parts) == 2:
                cond = _latex_to_unicode(parts[1].strip())
                val = _latex_to_unicode(parts[0].strip())
                rendered.append(f"{val}  当  {cond}")
            else:
                rendered.append(_latex_to_unicode(row.strip()))
        return " { " + " ; ".join(rendered) + " }"
    s = re.sub(r"\\begin\{cases\}(.*?)\\end\{cases\}", _cases_repl, s, flags=re.DOTALL)

    # 0.6 处理 \lim_{x \to a}（极限）
    # 纯 Unicode 下标紧凑表示：limₙ→∞（无花括号，不可映射字符保留原字符）
    def _lim_repl(m):
        sub = m.group(1)
        sub_u = _latex_to_unicode(sub)
        # 逐字符映射为 Unicode 真下标，不可映射字符保留原字符
        result = "".join(_LATEX_SUBSCRIPT.get(ch, ch) for ch in sub_u)
        return "lim" + result
    s = re.sub(r"\\lim_\{([^{}]*)\}", _lim_repl, s)
    s = re.sub(r"\\lim_([a-zA-Z])",
               lambda m: "lim" + _LATEX_SUBSCRIPT.get(m.group(1), m.group(1)), s)

    # 0.7 处理 \sum_{...}^{...} \prod_{...}^{...} \int_{...}^{...} 上下限
    # 纯 Unicode 上下标紧凑表示：Σᵢ₌₁ⁿ（无花括号，不可映射字符保留原字符）
    def _bigop_repl(m):
        op = m.group(1)
        # 补全反斜杠查找运算符符号
        op_u = _LATEX_OPERATORS.get("\\" + op, op)
        low = m.group(2) if m.group(2) else ""
        high = m.group(3) if m.group(3) else ""
        low_u = _latex_to_unicode(low) if low else ""
        high_u = _latex_to_unicode(high) if high else ""
        # 逐字符映射为 Unicode 真下标/上标，不可映射字符保留原字符
        low_result = "".join(_LATEX_SUBSCRIPT.get(ch, ch) for ch in low_u)
        high_result = "".join(_LATEX_SUPERSCRIPT.get(ch, ch) for ch in high_u)
        return f"{op_u}{low_result}{high_result}"
    s = re.sub(r"\\(sum|prod|coprod|int|oint|bigcup|bigcap|bigoplus|bigotimes)_\{([^{}]*)\}\^\{([^{}]*)\}",
               _bigop_repl, s)
    # 单独下标：group(3) 不存在，用空字符串
    def _bigop_low_only(m):
        class _M:
            def group(self, i):
                return [m.group(1), m.group(2), ""][i-1]
        return _bigop_repl(_M())
    s = re.sub(r"\\(sum|prod|coprod|int|oint|bigcup|bigcap|bigoplus|bigotimes)_\{([^{}]*)\}",
               _bigop_low_only, s)
    # 单独上标：group(2) 不存在，用空字符串
    def _bigop_high_only(m):
        class _M:
            def group(self, i):
                return [m.group(1), "", m.group(2)][i-1]
        return _bigop_repl(_M())
    s = re.sub(r"\\(sum|prod|coprod|int|oint|bigcup|bigcap|bigoplus|bigotimes)\^\{([^{}]*)\}",
               _bigop_high_only, s)

    # 1. 处理 \text{...} → 原样输出
    s = re.sub(r"\\text\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\mathbf\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\mathit\{([^}]*)\}", r"\1", s)

    # 2. 处理 \sqrt[n]{x}（n次根号）
    def _sqrt_n(m):
        n = m.group(1)
        body = _latex_to_unicode(m.group(2))
        root_sym = {"2": "√", "3": "∛", "4": "∜"}.get(n, "√")
        return f"{root_sym}({body})"
    s = re.sub(r"\\sqrt\[([^\]]+)\]\{([^{}]*)\}", _sqrt_n, s)

    # 3. 处理 \sqrt{x}（平方根）
    def _sqrt_simple(m):
        body = _latex_to_unicode(m.group(1))
        return f"√({body})"
    s = re.sub(r"\\sqrt\{([^{}]*)\}", _sqrt_simple, s)

    # 4. 处理 \frac{a}{b}（分数）
    # 使用 Unicode 分数斜杠 ⁄ (U+2044) 代替普通 / ，视觉上更接近真分数
    # 嵌套分数用不同括号区分层次：最内层()，中层[]，外层〔〕
    _FRAC_SLASH = "⁄"  # 分数斜杠（比普通 / 更短、更贴近真分数排版）
    def _frac(m):
        # 去除空格（LaTeX 中 \partial f 表示 ∂f，无空格）
        num = _latex_to_unicode(m.group(1)).replace(" ", "")
        den = _latex_to_unicode(m.group(2)).replace(" ", "")
        # 判断是否嵌套：分子或分母中已含分数斜杠 ⁄
        is_nested = "⁄" in num or "⁄" in den
        # 简单情况用 a⁄b（无括号）
        if len(num) <= 2 and len(den) <= 2 and not is_nested:
            return f"{num}{_FRAC_SLASH}{den}"
        # 嵌套用 []，非嵌套用 ()
        if is_nested:
            return f"〔{num}〕{_FRAC_SLASH}〔{den}〕"
        return f"({num}){_FRAC_SLASH}({den})"
    # 反复处理嵌套分数（8 轮覆盖学术公式嵌套深度）
    for _ in range(8):
        new_s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", _frac, s)
        if new_s == s:
            break
        s = new_s

    # 5. 处理 \binom{n}{k}（二项式系数）
    def _binom(m):
        return f"C({_latex_to_unicode(m.group(1))},{_latex_to_unicode(m.group(2))})"
    s = re.sub(r"\\binom\{([^{}]*)\}\{([^{}]*)\}", _binom, s)

    # 6. 处理 \mathbb{X}（黑板粗体）
    def _mathbb(m):
        ch = m.group(1)
        return _LATEX_OPERATORS.get(rf"\mathbb{{{ch}}}", ch)
    s = re.sub(r"\\mathbb\{([A-Z])\}", _mathbb, s)

    # 7. 替换希腊字母和运算符（按长度降序，避免 \alpha 被 \a 截断）
    # 必须在函数名替换之前，否则 \inf 会匹配 \infty 的前缀
    all_symbols = {**_LATEX_GREEK, **_LATEX_OPERATORS}
    for latex_cmd in sorted(all_symbols.keys(), key=len, reverse=True):
        if latex_cmd in s:
            s = s.replace(latex_cmd, all_symbols[latex_cmd])

    # 8. 处理函数名 \sin \cos 等（替换为纯文本，去掉反斜杠）
    for fn in _LATEX_FUNCTIONS:
        if fn in s:
            s = s.replace(fn, fn[1:])

    # 9. 处理上标 ^{...} 和 ^x
    def _sup_braced(m):
        content = m.group(1)
        # 递归处理内容（如 e^{-x^2} 中的 -x^2）
        content_u = _latex_to_unicode(content)
        result = ""
        for ch in content_u:
            result += _LATEX_SUPERSCRIPT.get(ch, ch)
        return result
    s = re.sub(r"\^\{([^{}]*)\}", _sup_braced, s)

    def _sup_single(m):
        ch = m.group(1)
        return _LATEX_SUPERSCRIPT.get(ch, f"^{ch}")
    s = re.sub(r"\^([a-zA-Z0-9+\-])", _sup_single, s)

    # 10. 处理下标 _{...} 和 _x
    def _sub_braced(m):
        content = m.group(1)
        # 递归处理内容
        content_u = _latex_to_unicode(content)
        # 检查是否所有字符都有 Unicode 下标映射
        all_mappable = all(ch in _LATEX_SUBSCRIPT for ch in content_u)
        if all_mappable:
            return "".join(_LATEX_SUBSCRIPT[ch] for ch in content_u)
        # 含未映射字符（如 b/c/d/f/g/q/r/w/y/z）→ 降级为 _{content}
        return f"_{{{content_u}}}"
    s = re.sub(r"_\{([^{}]*)\}", _sub_braced, s)

    def _sub_single(m):
        ch = m.group(1)
        return _LATEX_SUBSCRIPT.get(ch, f"_{ch}")
    s = re.sub(r"_([a-zA-Z0-9+\-])", _sub_single, s)

    # 11. 清理 LaTeX 空格命令 \, \; \: \! \quad \qquad
    s = re.sub(r"\\[,;:!]", " ", s)
    s = re.sub(r"\\quad\b", "  ", s)
    s = re.sub(r"\\qquad\b", "    ", s)
    # 清理 LaTeX 换行符 \\（含带间距版本 \\[2em]）和反斜杠空格 \ （必须在 \字母 清理之前）
    # \\[2em] → 换行；\\ → 换行；\ （反斜杠+空格）→ 空格
    s = re.sub(r"\\\\\[[^\]]*\]", "\n", s)   # \\[2em] 带间距换行
    s = re.sub(r"\\\\", "\n", s)             # \\ 换行
    s = re.sub(r"\\\s+", " ", s)             # \ + 空格（LaTeX 空格命令）
    # 清理剩余的 LaTeX 命令（\xxx 形式，保留文本）
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    # 清理孤立的反斜杠（\ + 非字母非数字非空格，如 \时 \趋近 等模型错误输出）
    s = re.sub(r"\\(?![a-zA-Z0-9\s])", "", s)

    # 12. 清理多余的空格和花括号
    # 清理花括号：保留 _{...} 和 ^{...} 中的花括号（LaTeX 风格下标/上标标记）
    # 只清理"独立的"花括号（不在 _ 或 ^ 后面的）
    s = re.sub(r"(?<![_^])\{([^{}]*)\}", r"\1", s)
    # 第二轮：清理剩余的独立花括号（第一轮可能产生新的独立花括号）
    s = re.sub(r"(?<![_^])\{([^{}]*)\}", r"\1", s)
    # 合并多余空格
    s = re.sub(r"  +", " ", s).strip()

    return s


def academic_search(query: str, num_results: int = 5, year_from: int = 0,
                    year_to: int = 0, sort_by: str = "relevance") -> str:
    """学术文献搜索（Semantic Scholar API，2亿+论文，含引用网络和影响力）

    参数：
    - query: 搜索关键词（中英文均可）
    - num_results: 返回结果数量，默认5，最大20
    - year_from: 起始年份（如 2020），0表示不限
    - year_to: 结束年份（如 2024），0表示不限
    - sort_by: 排序方式：relevance(相关性，默认) / citations(引用数) / influence(影响力)

    返回：格式化的文献列表，含标题、作者、年份、引用数、摘要、DOI

    迁移来源：tui_agent.py 行 4392-4491
    """
    try:
        q = urllib.parse.quote(query)
        # 构建年份过滤
        year_filter = ""
        if year_from or year_to:
            yf = year_from if year_from else 1900
            yt = year_to if year_to else 2099
            year_filter = f"&year={yf}-{yt}"

        # 排序参数
        sort_map = {
            "relevance": "",  # 默认相关性
            "citations": "&sort=citationCount:desc",
            "influence": "&sort=influentialCitationCount:desc",
        }
        sort_param = sort_map.get(sort_by, "")

        # Semantic Scholar Graph API（无需 API Key，免费 2万次/小时）
        url = (f"https://api.semanticscholar.org/graph/v1/paper/search?query={q}"
               f"&limit={min(num_results, 20)}&fields=title,authors,year,abstract,"
               f"citationCount,influentialCitationCount,externalIds,url"
               f"{year_filter}{sort_param}")

        req = urllib.request.Request(url, headers={
            "User-Agent": "ZeroAI/1.0 (Academic Research)",
            "Accept": "application/json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        papers = data.get("data", [])
        if not papers:
            return f"(未找到关于「{query}」的学术文献，试试更换关键词或扩大年份范围)"

        results = []
        for i, p in enumerate(papers, 1):
            title = p.get("title", "无标题")
            authors = p.get("authors", [])
            author_str = ", ".join(a.get("name", "?") for a in authors[:5])
            if len(authors) > 5:
                author_str += f" 等 {len(authors)} 人"
            year = p.get("year", "未知年份")
            citations = p.get("citationCount", 0)
            influential = p.get("influentialCitationCount", 0)
            abstract = p.get("abstract", "")
            if abstract:
                # 摘要截断到300字
                abstract = abstract[:300] + ("..." if len(abstract) > 300 else "")
            else:
                abstract = "(无摘要)"

            ext_ids = p.get("externalIds", {})
            doi = ext_ids.get("DOI", "")
            arxiv_id = ext_ids.get("ArXiv", "")
            paper_url = p.get("url", "")

            # 格式化输出
            line = f"[{i}] {title}\n"
            line += f"    作者: {author_str}\n"
            line += f"    年份: {year}    引用: {citations}    影响力: {influential}\n"
            if doi:
                line += f"    DOI: {doi}\n"
            if arxiv_id:
                line += f"    arXiv: {arxiv_id}\n"
            if paper_url:
                line += f"    链接: {paper_url}\n"
            line += f"    摘要: {abstract}\n"
            results.append(line)

        total = data.get("total", 0)
        header = f"=== 学术搜索: 「{query}」 ===\n"
        header += f"共找到 {total} 篇相关论文，显示前 {len(papers)} 篇"
        if year_from or year_to:
            header += f"（年份: {year_from or '不限'}-{year_to or '至今'}"
        if sort_by != "relevance":
            sort_label = {"citations": "引用数", "influence": "影响力"}.get(sort_by, sort_by)
            header += f"，按{sort_label}排序"
        header += "）\n\n"

        return header + "\n".join(results)

    except urllib.error.HTTPError as e:
        if e.code == 429:
            return f"学术搜索过于频繁，请稍后再试（Semantic Scholar 限制: 2万次/小时）"
        return f"学术搜索错误（HTTP {e.code}）：{e}"
    except Exception as e:
        return f"学术搜索错误：{e}"


def arxiv_search(query: str, num_results: int = 5, sort_by: str = "relevance",
                 category: str = "") -> str:
    """arXiv 预印本论文搜索（物理/数学/计算机科学/定量生物学/定量金融/统计学）

    参数：
    - query: 搜索关键词（英文效果更佳，支持标题/摘要/作者搜索）
    - num_results: 返回结果数量，默认5，最大20
    - sort_by: 排序方式：relevance(相关性，默认) / submittedDate(最新提交) / lastUpdatedDate(最近更新)
    - category: 学科分类筛选，如 cs.AI(人工智能) / cs.CL(计算语言学) / math.AG(代数几何) /
                physics(物理) / stat.ML(统计机器学习)。留空表示不限

    返回：格式化的论文列表，含标题、作者、摘要、arXiv ID、提交日期、PDF链接

    迁移来源：tui_agent.py 行 4494-4596
    """
    try:
        q = urllib.parse.quote(query)
        # 排序参数
        sort_map = {
            "relevance": "relevance",
            "submittedDate": "submittedDate",
            "lastUpdatedDate": "lastUpdatedDate",
        }
        sort_param = sort_map.get(sort_by, "relevance")

        # 分类筛选
        cat_filter = f"cat:{category}" if category else "all"

        # arXiv API（Atom XML 格式，完全免费）
        url = (f"http://export.arxiv.org/api/query?search_query={cat_filter}:{q}"
               f"&start=0&max_results={min(num_results, 20)}"
               f"&sortBy={sort_param}&sortOrder=descending")

        req = urllib.request.Request(url, headers={
            "User-Agent": "ZeroAI/1.0 (Academic Research)",
            "Accept": "application/atom+xml"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode("utf-8", errors="ignore")

        # 解析 Atom XML（用正则避免引入 xml.etree，保持轻量）
        entries = re.findall(r'<entry>([\s\S]*?)</entry>', xml_data)
        if not entries:
            return f"(未找到关于「{query}」的 arXiv 论文，试试用英文关键词)"

        results = []
        for i, entry in enumerate(entries, 1):
            # 提取标题
            title_m = re.search(r'<title>([\s\S]*?)</title>', entry)
            title = title_m.group(1).strip() if title_m else "无标题"
            title = re.sub(r'\s+', ' ', title)  # 清理换行

            # 提取作者
            authors = re.findall(r'<name>([^<]+)</name>', entry)
            author_str = ", ".join(authors[:5])
            if len(authors) > 5:
                author_str += f" 等 {len(authors)} 人"

            # 提取摘要
            summary_m = re.search(r'<summary>([\s\S]*?)</summary>', entry)
            abstract = summary_m.group(1).strip() if summary_m else "(无摘要)"
            abstract = re.sub(r'<[^>]+>', '', abstract)
            abstract = re.sub(r'\s+', ' ', abstract)
            if len(abstract) > 300:
                abstract = abstract[:300] + "..."

            # 提取 arXiv ID 和链接
            id_m = re.search(r'<id>http://arxiv.org/abs/([^<]+)</id>', entry)
            arxiv_id = id_m.group(1).strip() if id_m else "未知"
            pdf_link = f"http://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id != "未知" else ""

            # 提取提交日期
            published_m = re.search(r'<published>([^<]+)</published>', entry)
            published = published_m.group(1)[:10] if published_m else "未知日期"

            # 提取分类
            categories = re.findall(r'term="([^"]+)"', entry)
            cat_str = ", ".join(categories[:3]) if categories else "未分类"

            # 格式化输出
            line = f"[{i}] {title}\n"
            line += f"    作者: {author_str}\n"
            line += f"    arXiv: {arxiv_id}    提交: {published}\n"
            line += f"    分类: {cat_str}\n"
            if pdf_link:
                line += f"    PDF: {pdf_link}\n"
            line += f"    摘要: {abstract}\n"
            results.append(line)

        total_m = re.search(r'<opensearch:totalResults[^>]*>([^<]+)</opensearch:totalResults>', xml_data)
        total = total_m.group(1) if total_m else str(len(entries))

        header = f"=== arXiv 搜索: 「{query}」 ===\n"
        header += f"共找到 {total} 篇预印本论文，显示前 {len(entries)} 篇"
        if category:
            header += f"（分类: {category}）"
        if sort_by != "relevance":
            sort_label = {"submittedDate": "最新提交", "lastUpdatedDate": "最近更新"}.get(sort_by, sort_by)
            header += f"，按{sort_label}排序"
        header += "\n\n"

        return header + "\n".join(results)

    except Exception as e:
        return f"arXiv 搜索错误：{e}"


def _format_citation_result(data: dict, method: str, query: str, similarity: float = 1.0) -> str:
    """格式化引用校验结果（citation_check 的辅助函数）

    迁移来源：tui_agent.py 行 4674-4712
    """
    title = data.get("title", "无标题")
    authors = data.get("authors", [])
    author_str = ", ".join(a.get("name", "?") for a in authors[:5])
    if len(authors) > 5:
        author_str += f" 等 {len(authors)} 人"
    year = data.get("year", "未知")
    citations = data.get("citationCount", 0)
    ext_ids = data.get("externalIds", {})
    doi = ext_ids.get("DOI", "")
    arxiv = ext_ids.get("ArXiv", "")
    paper_url = data.get("url", "")

    # 判定状态
    if similarity >= 0.95:
        status = "✓ 验证通过：文献真实存在（标题精确匹配）"
    elif similarity >= 0.80:
        status = f"✓ 验证通过：文献真实存在（标题相似度 {similarity:.0%}，请核实标题是否完全一致）"
    elif similarity >= 0.60:
        status = f"⚠ 部分匹配（相似度 {similarity:.0%}）：找到相关文献，但标题不完全一致，请核实是否为同一篇"
    else:
        status = f"⚠ 匹配度低（{similarity:.0%}）：可能不是同一篇文献，请人工核实"

    result = f"=== 引用校验结果 ===\n"
    result += f"校验方式：{method}\n"
    result += f"查询条件：{query}\n"
    result += f"状态：{status}\n\n"
    result += f"文献信息：\n"
    result += f"  标题：{title}\n"
    result += f"  作者：{author_str}\n"
    result += f"  年份：{year}    引用数：{citations}\n"
    if doi:
        result += f"  DOI：{doi}\n"
    if arxiv:
        result += f"  arXiv：{arxiv}\n"
    if paper_url:
        result += f"  链接：{paper_url}\n"
    return result


def citation_check(title: str = "", doi: str = "", arxiv_id: str = "") -> str:
    """校验文献引用真实性（防止 AI 编造不存在的文献）

    通过 Semantic Scholar API 交叉验证文献是否真实存在。
    支持三种查询方式：标题精确匹配、DOI 查询、arXiv ID 查询。

    参数：
    - title: 文献标题（精确或近似标题）
    - doi: 文献的 DOI（如 10.1038/s41586-021-03819-2）
    - arxiv_id: arXiv 编号（如 2301.00234）

    返回：校验结果，含文献真实状态、正确标题、作者、年份等元数据

    迁移来源：tui_agent.py 行 4599-4671
    """
    try:
        # 优先用 DOI 查询（最精确）
        if doi:
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}?fields=title,authors,year,abstract,citationCount,externalIds,url"
            req = urllib.request.Request(url, headers={
                "User-Agent": "ZeroAI/1.0 (Academic Citation Check)",
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return _format_citation_result(data, "DOI", doi)

        # arXiv ID 查询
        if arxiv_id:
            url = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id.strip()}?fields=title,authors,year,abstract,citationCount,externalIds,url"
            req = urllib.request.Request(url, headers={
                "User-Agent": "ZeroAI/1.0 (Academic Citation Check)",
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return _format_citation_result(data, "arXiv", arxiv_id)

        # 标题查询（模糊匹配）
        if title:
            q = urllib.parse.quote(title)
            url = f"https://api.semanticscholar.org/graph/v1/paper/search/match?query={q}&fields=title,authors,year,abstract,citationCount,externalIds,url"
            req = urllib.request.Request(url, headers={
                "User-Agent": "ZeroAI/1.0 (Academic Citation Check)",
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))

            papers = data.get("data", [])
            if papers:
                # 找最匹配的
                best = papers[0]
                # 计算标题相似度
                from difflib import SequenceMatcher
                ratio = SequenceMatcher(None, title.lower().strip(), best.get("title", "").lower().strip()).ratio()
                return _format_citation_result(best, "标题匹配", title, similarity=ratio)
            else:
                return (f"⚠ 引用校验失败：未找到与「{title}」匹配的论文\n"
                        f"  该引用可能为 AI 编造的虚构文献，请勿使用\n"
                        f"  建议：使用 academic_search 搜索真实存在的文献替代")

        return "请提供文献标题、DOI 或 arXiv ID 中的至少一个参数"

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return (f"✗ 引用校验结果：文献不存在\n"
                    f"  查询条件：{('DOI:' + doi) if doi else ('arXiv:' + arxiv_id) if arxiv_id else ('标题:' + title)}\n"
                    f"  该引用很可能是 AI 编造的虚构文献，请勿在学术写作中使用\n"
                    f"  建议：使用 academic_search 搜索该领域的真实文献")
        if e.code == 429:
            return "引用校验过于频繁，请稍后再试（Semantic Scholar 限制: 2万次/小时）"
        return f"引用校验错误（HTTP {e.code}）：{e}"
    except Exception as e:
        return f"引用校验错误：{e}"


def _lit_review_search_ss(topic: str, num: int, year_from: int, year_to: int) -> list:
    """literature_review 辅助：从 Semantic Scholar 检索

    迁移来源：tui_agent.py 行 4866-4900
    """
    papers = []
    try:
        q = urllib.parse.quote(topic)
        year_filter = ""
        if year_from or year_to:
            yf = year_from if year_from else 1900
            yt = year_to if year_to else 2099
            year_filter = f"&year={yf}-{yt}"
        url = (f"https://api.semanticscholar.org/graph/v1/paper/search?query={q}"
               f"&limit={min(num, 20)}&fields=title,authors,year,abstract,citationCount,externalIds,url"
               f"{year_filter}&sort=citationCount:desc")
        req = urllib.request.Request(url, headers={
            "User-Agent": "ZeroAI/1.0 (Academic Literature Review)",
            "Accept": "application/json"
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        for p in data.get("data", []):
            ext = p.get("externalIds", {})
            papers.append({
                "title": p.get("title", ""),
                "authors": p.get("authors", []),
                "year": p.get("year", 0),
                "citations": p.get("citationCount", 0),
                "abstract": p.get("abstract", ""),
                "doi": ext.get("DOI", ""),
                "arxiv_id": ext.get("ArXiv", ""),
                "url": p.get("url", ""),
                "source": "Semantic Scholar",
            })
    except Exception:
        pass
    return papers


def _lit_review_search_arxiv(topic: str, num: int) -> list:
    """literature_review 辅助：从 arXiv 检索最新论文

    迁移来源：tui_agent.py 行 4903-4942
    """
    papers = []
    try:
        q = urllib.parse.quote(topic)
        # 用 all: 搜索 + relevance 排序（确保结果相关性）
        url = (f"http://export.arxiv.org/api/query?search_query=all:{q}"
               f"&start=0&max_results={min(num, 10)}"
               f"&sortBy=relevance&sortOrder=descending")
        req = urllib.request.Request(url, headers={
            "User-Agent": "ZeroAI/1.0 (Academic Literature Review)",
            "Accept": "application/atom+xml"
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_data = resp.read().decode("utf-8", errors="ignore")
        entries = re.findall(r'<entry>([\s\S]*?)</entry>', xml_data)
        for entry in entries:
            title_m = re.search(r'<title>([\s\S]*?)</title>', entry)
            title = re.sub(r'\s+', ' ', title_m.group(1).strip()) if title_m else ""
            authors = re.findall(r'<name>([^<]+)</name>', entry)
            summary_m = re.search(r'<summary>([\s\S]*?)</summary>', entry)
            abstract = re.sub(r'\s+', ' ', summary_m.group(1).strip()) if summary_m else ""
            id_m = re.search(r'<id>http://arxiv.org/abs/([^<]+)</id>', entry)
            arxiv_id = id_m.group(1).strip() if id_m else ""
            published_m = re.search(r'<published>([^<]+)</published>', entry)
            year = int(published_m.group(1)[:4]) if published_m else 0
            papers.append({
                "title": title,
                "authors": [{"name": a} for a in authors],
                "year": year,
                "citations": 0,
                "abstract": abstract,
                "doi": "",
                "arxiv_id": arxiv_id,
                "url": f"http://arxiv.org/abs/{arxiv_id}",
                "source": "arXiv",
            })
    except Exception:
        pass
    return papers


def literature_review(topic: str, num_papers: int = 10, year_from: int = 0,
                      year_to: int = 0) -> str:
    """多文献综合对比分析（自动检索+结构化对比+研究空白识别）

    自动执行完整的文献综述流程：
    1. 检索相关文献（Semantic Scholar + arXiv 双源）
    2. 按引用数筛选高质量文献
    3. 结构化提取每篇文献的方法/结论/局限
    4. 生成对比分析表
    5. 识别研究空白和未来方向

    参数：
    - topic: 研究主题（中英文均可，如 '钠离子电池层状氧化物正极' 或 'sodium-ion battery layered oxide cathode'）
    - num_papers: 分析文献数量，默认10，最大20
    - year_from: 起始年份（如 2018），0表示不限
    - year_to: 结束年份（如 2025），0表示不限

    返回：结构化文献综述分析报告

    迁移来源：tui_agent.py 行 4715-4863
    """
    try:
        # ── 第1步：双源检索 ──
        all_papers = []

        # Semantic Scholar（按引用数排序，筛选高影响力文献）
        ss_papers = _lit_review_search_ss(topic, num_papers, year_from, year_to)
        all_papers.extend(ss_papers)

        # arXiv（最新研究，按提交日期排序）
        arxiv_papers = _lit_review_search_arxiv(topic, min(num_papers // 2, 5))
        all_papers.extend(arxiv_papers)

        if not all_papers:
            return (f"=== 文献综述分析：{topic} ===\n\n"
                    f"未找到相关文献，请尝试更换关键词或扩大年份范围\n"
                    f"建议：使用英文关键词（如 'sodium-ion battery cathode'）效果更佳")

        # ── 第2步：去重（按标题模糊匹配） ──
        from difflib import SequenceMatcher
        unique_papers = []
        seen_titles = []
        for p in all_papers:
            is_dup = False
            for seen in seen_titles:
                if SequenceMatcher(None, p.get("title", "").lower(), seen.lower()).ratio() > 0.85:
                    is_dup = True
                    break
            if not is_dup:
                unique_papers.append(p)
                seen_titles.append(p.get("title", ""))

        # 按引用数排序，取前 num_papers 篇
        unique_papers.sort(key=lambda x: x.get("citations", 0), reverse=True)
        top_papers = unique_papers[:num_papers]

        # ── 第3步：生成综述报告 ──
        report = f"=== 文献综述分析报告 ===\n"
        report += f"研究主题：{topic}\n"
        report += f"检索范围：{year_from or '不限'} - {year_to or '至今'}\n"
        report += f"分析文献数：{len(top_papers)} 篇（去重后共 {len(unique_papers)} 篇）\n"
        report += f"数据来源：Semantic Scholar + arXiv\n\n"

        # ── 文献概览表 ──
        report += "── 一、文献概览 ──\n\n"
        report += f"{'#':<4} {'年份':<6} {'引用':<8} {'标题':<50} {'来源':<12}\n"
        report += "-" * 85 + "\n"
        for i, p in enumerate(top_papers, 1):
            title_short = p.get("title", "无标题")[:48]
            year = str(p.get("year", "?"))[:4]
            cit = str(p.get("citations", 0))[:7]
            source = p.get("source", "?")[:10]
            report += f"{i:<4} {year:<6} {cit:<8} {title_short:<50} {source:<12}\n"

        # ── 详细分析 ──
        report += "\n── 二、逐篇分析 ──\n\n"
        for i, p in enumerate(top_papers, 1):
            report += f"[{i}] {p.get('title', '无标题')}\n"
            authors = p.get("authors", [])
            author_str = ", ".join(a if isinstance(a, str) else a.get("name", "?") for a in authors[:5])
            if len(authors) > 5:
                author_str += f" 等 {len(authors)} 人"
            report += f"    作者：{author_str}\n"
            report += f"    年份：{p.get('year', '?')}    引用数：{p.get('citations', 0)}\n"

            doi = p.get("doi", "")
            arxiv = p.get("arxiv_id", "")
            if doi:
                report += f"    DOI：{doi}\n"
            if arxiv:
                report += f"    arXiv：{arxiv}\n"

            abstract = p.get("abstract", "") or p.get("summary", "")
            if abstract:
                abstract = abstract[:400] + ("..." if len(abstract) > 400 else "")
                report += f"    摘要：{abstract}\n"
            report += "\n"

        # ── 研究趋势分析 ──
        report += "── 三、研究趋势分析 ──\n\n"
        years = [p.get("year", 0) for p in top_papers if p.get("year")]
        if years:
            y_min, y_max = min(years), max(years)
            report += f"时间跨度：{y_min} - {y_max}\n"
            # 按年份统计
            year_dist = {}
            for y in years:
                year_dist[y] = year_dist.get(y, 0) + 1
            report += "年度分布：\n"
            for y in sorted(year_dist.keys()):
                bar = "█" * year_dist[y]
                report += f"  {y}: {bar} ({year_dist[y]}篇)\n"

        # 引用分析
        total_cit = sum(p.get("citations", 0) for p in top_papers)
        avg_cit = total_cit / len(top_papers) if top_papers else 0
        report += f"\n总引用数：{total_cit}    平均引用：{avg_cit:.1f}\n"

        # ── 研究空白与未来方向 ──
        report += "\n── 四、研究空白与未来方向（自动识别） ──\n\n"
        report += "基于检索到的文献，以下方向值得关注（需结合专业知识进一步验证）：\n"
        # 基于文献年份和引用数推断
        recent_papers = [p for p in top_papers if p.get("year", 0) >= 2023]
        if recent_papers:
            report += f"1. 近期热点（{len(recent_papers)}篇2023年后文献）：关注该领域最新进展\n"
        old_high_cit = [p for p in top_papers if p.get("year", 0) < 2020 and p.get("citations", 0) > 100]
        if old_high_cit:
            report += f"2. 经典基础（{len(old_high_cit)}篇高引经典）：建议深入阅读这些奠基性工作\n"
        low_cit_recent = [p for p in top_papers if p.get("year", 0) >= 2022 and p.get("citations", 0) < 10]
        if low_cit_recent:
            report += f"3. 新兴方向（{len(low_cit_recent)}篇低引新文）：可能代表尚未被广泛关注的研究前沿\n"
        report += "4. 交叉领域：结合本主题与其他学科（如AI/材料/工程）的交叉研究\n"
        report += "5. 方法论改进：现有方法的局限性可作为改进方向\n\n"

        # ── PRISMA 筛选流程 ──
        report += "── 五、PRISMA 筛选流程 ──\n\n"
        report += f"检索总量：{len(all_papers)} 篇\n"
        report += f"去重后：{len(unique_papers)} 篇（去除 {len(all_papers) - len(unique_papers)} 篇重复）\n"
        report += f"纳入分析：{len(top_papers)} 篇（按引用数筛选）\n"
        report += f"排除：{len(unique_papers) - len(top_papers)} 篇（引用数较低）\n\n"

        report += "── 注意事项 ──\n"
        report += "1. 本分析基于自动检索结果，不含人工筛选和质量评估\n"
        report += "2. 建议在此基础上人工精读 top 3-5 篇高引文献\n"
        report += "3. 如需正式发表，请补充 Web of Science / Scopus 检索\n"
        report += "4. 引用文献时务必使用 citation_check 校验真实性\n"

        return report

    except Exception as e:
        return f"文献综述分析错误：{e}"


def render_formula(latex: str, style: str = "unicode") -> str:
    r"""渲染 LaTeX 公式为终端可显示的 Unicode 文本

    参数：
    - latex: LaTeX 公式字符串，如 "E=mc^2" 或 "\\sum_{i=1}^{n} x_i^2"
    - style: 渲染样式
      - "unicode"：纯 Unicode 数学符号（默认，终端显示）
      - "raw"：返回原始 LaTeX（用于文档生成）
      - "latex"：用 $$ 包裹（用于 Markdown 渲染）

    返回：渲染后的公式字符串

    用途：学术研究、数学公式展示、物理方程推导

    迁移来源：tui_agent.py 行 4945-4972
    """
    latex = latex.strip()
    # 去除外层 $ 或 $$
    if latex.startswith("$$") and latex.endswith("$$"):
        latex = latex[2:-2].strip()
    elif latex.startswith("$") and latex.endswith("$"):
        latex = latex[1:-1].strip()

    if style == "raw":
        return latex
    elif style == "latex":
        return f"$${latex}$$"
    else:  # unicode
        rendered = _latex_to_unicode(latex)
        return rendered
