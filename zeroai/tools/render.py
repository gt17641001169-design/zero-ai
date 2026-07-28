"""Markdown 渲染工具

迁移来源：tui_agent.py 行 3444-3589, 5085-5115, 10023-10033

提供以下纯函数：
- _safe_markdown：安全构造 Markdown 渲染对象
- _normalize_markdown_for_academic：学术 Markdown 规范化预处理
- render_image_preview：终端图片预览
- render_latex_in_text：文本 LaTeX 渲染
- render_markdown：Markdown 渲染入口

依赖：
- 标准库：re, base64
- rich.text.Text, rich.markdown.Markdown
- .academic._latex_to_unicode（延迟 import 避免循环）

注意：C_DIM 为配色常量（迁移来源 tui_agent.py 行 1787），本模块内置定义以避免依赖 TUI 层。
"""
import re
import base64

from rich.text import Text


# 配色常量（迁移来源：tui_agent.py 行 1787）
# 灰色（次要文字/说明）
C_DIM = "#6B6B75"


def _normalize_markdown_for_academic(text: str) -> str:
    """学术 Markdown 规范化预处理
    - 去除标题行首空格（避免 `   ## 标题` 被当代码块）
    - 标题前后补空行（确保渲染正确）
    - 五级及以上标题降级为加粗正文
    - 清理空标题（连续的 # 字符）

    迁移来源：tui_agent.py 行 3470-3520
    """
    lines = text.split("\n")
    normalized = []
    prev_was_heading = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        # 匹配标题：# 标题、## 标题、### 标题、#### 标题、##### 标题...
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            hashes, title_text = m.group(1), m.group(2).strip()
            # 清理空标题（只有 # 没有文字）
            if not title_text or title_text.strip("#").strip() == "":
                continue
            # 五级及以上降级为加粗正文
            if len(hashes) >= 5:
                normalized.append("")  # 标题前空行
                normalized.append(f"**{title_text}**")
                normalized.append("")  # 标题后空行
                prev_was_heading = True
                continue
            # 标题前补空行（如果上一行不是空行）
            if normalized and normalized[-1].strip() != "" and not prev_was_heading:
                normalized.append("")
            normalized.append(f"{hashes} {title_text}")
            prev_was_heading = True
        else:
            # 非标题行
            if prev_was_heading and line.strip() == "":
                # 标题后第一个空行，标记为已分隔
                pass
            prev_was_heading = False
            normalized.append(line)
    # 清理连续空行（最多保留 2 个）
    result = []
    blank_count = 0
    for ln in normalized:
        if ln.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                result.append(ln)
        else:
            blank_count = 0
            result.append(ln)
    return "\n".join(result)


def _safe_markdown(text, code_theme: str = None):
    """安全构造 Markdown 渲染对象

    关键点：Textual 8.x 的 `textual.widgets.Markdown` 是一个 Widget（不可作为 renderable），
    只能在 `mount()` 时使用。但用户调用方大多是 `Static.update()` / `log.write()`，
    这些需要的是 Rich 的 `Markdown` renderable。

    因此本函数始终返回 `rich.markdown.Markdown` 实例（兼容所有 Textual 版本）。
    `code_theme` 参数在 rich.markdown 中不支持（rich 直接用 Pygments 主题），
    保留参数仅为了兼容旧调用点。

    同时对输入做学术规范化预处理：
    - 去除标题行首的空格/制表符（避免被误判为代码块）
    - 标题前后自动补空行
    - 五级及以上标题降级为加粗正文（学术论文不应使用）

    迁移来源：tui_agent.py 行 3444-3467
    """
    if text:
        text = _normalize_markdown_for_academic(text)
    try:
        from rich.markdown import Markdown as RichMarkdown
        return RichMarkdown(text or "")
    except Exception:
        # 最后兜底：返回纯文本（保证类型是 str）
        return text or ""


def render_image_preview(image_source: str, max_width: int = 50) -> Text:
    """在终端中用半块字符渲染图片预览
    image_source: base64 data URI 或文件路径
    max_width: 预览最大字符宽度
    返回: Rich Text 对象，包含彩色图片预览

    迁移来源：tui_agent.py 行 3523-3589
    """
    try:
        from PIL import Image
        import io

        # 加载图片
        if image_source.startswith("data:"):
            # data URI 格式
            header, b64data = image_source.split(",", 1)
            img_data = base64.b64decode(b64data)
            img = Image.open(io.BytesIO(img_data))
        else:
            # 文件路径
            img = Image.open(image_source)

        # 转为 RGB 模式（去掉 alpha 通道，透明背景用黑色填充）
        if img.mode == "RGBA":
            background = Image.new("RGBA", img.size, (0, 0, 0, 255))
            background.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
            img = background.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 计算缩放尺寸：每个字符代表2个垂直像素
        # 保持宽高比，宽度不超过 max_width
        orig_w, orig_h = img.size
        char_width = min(max_width, orig_w)
        char_height = max(1, int(char_width * orig_h / orig_w / 2))
        pixel_width = char_width
        pixel_height = char_height * 2  # 每个字符2个像素行

        img_small = img.resize((pixel_width, pixel_height), Image.LANCZOS)
        pixels = list(img_small.getdata())

        # 用 Rich Text 渲染：▀ 字符前景=上像素，背景=下像素
        result = Text()
        for row in range(char_height):
            line_text = ""
            spans = []
            for col in range(char_width):
                # 上像素
                idx_top = row * 2 * pixel_width + col
                # 下像素
                idx_bot = (row * 2 + 1) * pixel_width + col
                r1, g1, b1 = pixels[idx_top][:3]
                r2, g2, b2 = pixels[idx_bot][:3]
                top_color = f"#{r1:02x}{g1:02x}{b1:02x}"
                bot_color = f"#{r2:02x}{g2:02x}{b2:02x}"
                # ▀ (U+2580) 上半块：前景=上像素颜色，背景=下像素颜色
                line_text += "▀"
                spans.append((top_color, bot_color))
            # 为整行添加样式
            # Rich 支持 style="fg color on bg color"
            # 每个字符需要不同的颜色，所以逐字符添加
            for i, ch in enumerate(line_text):
                top_c, bot_c = spans[i]
                result.append(ch, style=f"{top_c} on {bot_c}")
            result.append("\n")

        return result
    except Exception as e:
        return Text(f"  [图片预览失败: {str(e)[:60]}]", style=C_DIM)


def render_latex_in_text(text: str) -> str:
    """检测文本中的 LaTeX 公式并渲染为 Unicode

    支持：
    - 行内公式：$E=mc^2$
    - 块级公式：$$\\int_0^1 f(x)dx$$
    - \\( \\) 行内公式
    - \\[ \\] 块级公式

    用于终端 Markdown 渲染前的预处理

    迁移来源：tui_agent.py 行 5085-5115
    """
    if not text or "$" not in text and "\\(" not in text and "\\[" not in text:
        return text

    # 延迟 import 避免循环依赖（academic.py 可能反向依赖 render.py）
    from .academic import _latex_to_unicode

    # 1. 块级公式 $$...$$
    def _block_formula(m):
        rendered = _latex_to_unicode(m.group(1))
        return f"\n   {rendered}\n"
    text = re.sub(r"\$\$([^$]+)\$\$", _block_formula, text)

    # 2. 块级公式 \[...\]
    text = re.sub(r"\\\[([^\]]+)\]", lambda m: f"\n   {_latex_to_unicode(m.group(1))}\n", text)

    # 3. 行内公式 \(...\)
    text = re.sub(r"\\\(([^)]+)\)", lambda m: _latex_to_unicode(m.group(1)), text)

    # 4. 行内公式 $...$（最后处理，避免误伤 $$）
    # 使用非贪婪匹配，且内容不含 $
    text = re.sub(r"(?<!\$)\$([^$\n]+)\$(?!\$)", lambda m: _latex_to_unicode(m.group(1)), text)

    return text


def render_markdown(text: str):
    r"""渲染 Markdown，代码块用语法高亮，自动渲染 LaTeX 公式

    学术研究支持：
    - 行内公式 $E=mc^2$ → E=mc²（Unicode 渲染）
    - 块级公式 $$\\sum_{i=1}^{n} x_i^2$$ → Σᵢ₌₁ⁿ xᵢ²
    - LaTeX 命令 \\alpha \\beta \\int \\sum 等自动转换为 Unicode 符号

    迁移来源：tui_agent.py 行 10023-10033
    """
    # 先渲染 LaTeX 公式为 Unicode，再交给 Markdown 渲染
    text = render_latex_in_text(text)
    return _safe_markdown(text, code_theme="monokai")
