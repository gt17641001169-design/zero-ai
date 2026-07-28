"""配置常量与专家团队定义

迁移来源：tui_agent.py 行 526-962, 1157-1172, 1426-1435, 1742-1747

提供：
- _BUILTIN_KEYS / _GLM_DEFAULT_KEY / _OR_DEFAULT_KEY：内置 API Key（混淆存储）
- MODEL_CONFIGS：模型后端配置（glm / glm-4 / glm-v / openrouter / ollama）
- OR_BASE / OR_KEY：OpenRouter 基础配置
- 混合思考模式参数：HYBRID_MAX_PARALLEL_EXPERTS 等
- EXPERT_TEAM：完整专家团队配置（含 system_prompt）
- WORK_MODE：工作模式（expert / hybrid / manual）
- 上下文压缩参数：CHARS_PER_TOKEN / COMPRESS_THRESHOLD_RATIO 等
- _VISION_MODEL_KEYWORDS / _MODEL_CONTEXT_LIMITS：模型能力识别
- PERMISSION_LEVEL / MAX_FILE_SIZE：权限与文件大小限制

依赖关系：
- 本模块从 secrets.py 导入 _deobfuscate / _get_api_key / _load_config
- secrets.py 不在模块级导入本模块，故无循环依赖
"""
from .secrets import _deobfuscate, _get_api_key, _load_config


# ====== 配置：模型后端（可切换）======
# 内置免费模型 API Key（混淆存储，运行时自动解混淆）
# 所有用户均可直接使用，无需自行配置
_BUILTIN_KEYS = {
    "glm": "YWY5MTJiYjI0NTQ5NDNhMGE2NGY1ZTJlZWU5YTRiZTQuZXVjOVgyd09DRWthTm5sQQ==",
    "openrouter": "c2stb3ItdjEtYWEzNmMyYzJhMzc4NDVlNzliNTI3MDVhMWE1MzU1NDQ1ZDJkMWFjOTk2NzcwNzkzMGZkMTU3N2U1MTg0YzE4NQ==",
}

# 内置默认 Key（从混淆值解出，用户配置的 Key 优先级更高）
_GLM_DEFAULT_KEY = _deobfuscate(_BUILTIN_KEYS["glm"])
_OR_DEFAULT_KEY = _deobfuscate(_BUILTIN_KEYS["openrouter"])

MODEL_CONFIGS = {
    "glm": {
        "label": "智谱GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "api_key": _get_api_key("glm", _GLM_DEFAULT_KEY),
        "model": "glm-4.7-flash",
    },
    "glm-4": {
        "label": "智谱GLM-4",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "api_key": _get_api_key("glm", _GLM_DEFAULT_KEY),  # 共用 GLM Key
        "model": "glm-4-flash",  # GLM-4 免费版，作为 GLM-4.7 限流时的降级目标（不同限流池）
    },
    "glm-v": {
        "label": "智谱GLM-4V",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "api_key": _get_api_key("glm", _GLM_DEFAULT_KEY),  # 共用 GLM Key
        "model": "glm-4v-flash",  # 免费多模态模型，支持图片输入
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": _get_api_key("openrouter", _OR_DEFAULT_KEY),
        "model": "openrouter/free",  # 自动路由到可用免费模型，避免单一模型限流
    },
    "ollama": {
        "label": "Ollama本地",
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "model": "gemma4:latest",
    },
}

# 如果智谱 Key 为空，尝试从旧配置迁移或使用内置 Key
if not MODEL_CONFIGS["glm"]["api_key"]:
    _old_config = _load_config()
    if "glm" in _old_config and _old_config["glm"].get("api_key"):
        MODEL_CONFIGS["glm"]["api_key"] = _old_config["glm"]["api_key"]
    else:
        # 回退到内置 Key（确保打包后所有人都能用）
        MODEL_CONFIGS["glm"]["api_key"] = _GLM_DEFAULT_KEY

# glm-v 共用 glm 的 Key（同一个智谱账号）
MODEL_CONFIGS["glm-v"]["api_key"] = MODEL_CONFIGS["glm"]["api_key"]

# 为 openrouter 迁移旧配置中的 Key
if not MODEL_CONFIGS["openrouter"]["api_key"]:
    _old_cfg = _load_config()
    if "openrouter" in _old_cfg and _old_cfg["openrouter"].get("api_key"):
        MODEL_CONFIGS["openrouter"]["api_key"] = _old_cfg["openrouter"]["api_key"]
    else:
        MODEL_CONFIGS["openrouter"]["api_key"] = _OR_DEFAULT_KEY

# ====== 专家团队配置 ======
# OpenRouter 免费模型（通过 openrouter 平台调用，只需切换 model 名称）
OR_BASE = "https://openrouter.ai/api/v1"
OR_KEY = MODEL_CONFIGS["openrouter"]["api_key"]

# ====== 混合思考模式配置 ======
# 专家并行度控制：最多同时调用的专家数（避免 token 暴涨）
HYBRID_MAX_PARALLEL_EXPERTS = 3
# 专家回答长度限制（字符数）：超过则截断，便于汇总
HYBRID_EXPERT_MAX_CHARS = 800
# 专家回答去重相似度阈值（0-1，Jaccard 相似度）：超过则视为重复
HYBRID_DEDUP_SIMILARITY_THRESHOLD = 0.7
# 专家记忆：每个专家保留的最近对话轮数（独立上下文，避免主上下文污染）
EXPERT_MEMORY_TURNS = 3
# 专家协作链：是否启用专家间结果传递（如 coder 写代码 → reasoner 审查）
HYBRID_ENABLE_COLLAB_CHAIN = False  # 默认关闭，避免 token 消耗翻倍

# 专家团队：每个专家对应一个模型配置
EXPERT_TEAM = {
    "pm": {  # 项目经理（多模态，支持图片）
        "label": "项目经理·GLM-4V",
        "model_key": "glm-v",
        "model": "glm-4v-flash",
        "desc": "任务分析·调度·多模态（支持图片）",
        "keywords": ["帮助", "分析", "计划", "总结", "翻译", "什么", "怎么", "如何", "介绍", "解释"],
        "system_prompt": "你是 ZeroAI 的项目经理，负责任务分析、计划制定、跨领域调度。用中文回答，简洁明了。如用户发送图片，请理解图片内容并纳入分析。",
    },
    "coder": {  # 编程专家（原 Nemotron-120B 已下线，替换为 GLM-4.7-Flash，智谱直供稳定）
        # 备份原配置：model_key="openrouter", model="nvidia/nemotron-3-super-120b-a12b:free"（已连接错误）
        "label": "编程·GLM-4.7",
        "model_key": "glm",
        "model": "glm-4.7-flash",
        "desc": "代码生成·调试·重构（GLM-4.7-Flash·智谱直供·免费无限）",
        "keywords": ["代码", "编程", "函数", "bug", "error", "python", "js", "java", "css", "html",
                      "sql", "api", "写一个", "实现", "debug", "code", "function", "class", "脚本"],
        "system_prompt": "你是 ZeroAI 的编程专家，专精代码生成、调试、重构、架构设计。直接给出可运行的代码，必要时简短说明思路。你是 ZeroAI，不是其他模型。",
    },
    "reasoner": {  # 推理专家（GLM-4.7-Flash，智谱直供稳定；OpenRouter Key 失效后切换）
        # 备份原配置：model_key="openrouter", model="nvidia/nemotron-3-ultra-550b-a55b:free"（Key 已失效 401）
        "label": "推理·GLM-4.7",
        "model_key": "glm",
        "model": "glm-4.7-flash",
        "desc": "深度推理·数学·逻辑（GLM-4.7-Flash·智谱直供·免费无限）",
        "keywords": ["推理", "证明", "数学", "计算", "逻辑", "为什么", "分析原因", "算法",
                      "复杂", "优化", "证明", "solve", "math", "reason"],
        "system_prompt": "你是 ZeroAI 的推理专家，专精深度推理、数学证明、复杂逻辑分析。给出严谨的推理过程和结论。你是 ZeroAI，不是其他模型。",
    },
    "knowledge": {  # 通用知识（GLM-4.7-Flash，智谱直供，免费无限，响应极快）
        "label": "通用·GLM-4.7",
        "model_key": "glm",
        "model": "glm-4.7-flash",
        "desc": "通用问答·翻译·百科（GLM-4.7-Flash·智谱直供·免费无限）",
        "keywords": [],  # 默认兜底
        "system_prompt": "你是 ZeroAI 的通用知识专家，负责回答百科类问题、事实查询、翻译等。给出准确、简洁的回答。",
    },
    "chinese": {  # 中文专家（GLM-4.7-Flash，智谱直供稳定；OpenRouter Key 失效后切换）
        # 备份原配置：model_key="openrouter", model="nvidia/nemotron-3-nano-30b-a3b:free"（Key 已失效 401）
        "label": "中文·GLM-4.7",
        "model_key": "glm",
        "model": "glm-4.7-flash",
        "desc": "中文写作·文案·报告（GLM-4.7-Flash·智谱直供·免费无限）",
        "keywords": ["写", "作文", "文章", "报告", "文案", "论文", "小说", "故事", "邮件",
                      "摘要", "润色", "写作", "中文"],
        "system_prompt": "你是 ZeroAI 的中文写作专家，专精文章、报告、文案、邮件、润色。直接输出高质量中文内容。你是 ZeroAI，不是其他模型。",
    },
    "vision": {  # 多模态（GLM-4V-Flash，智谱直供，免费多模态，稳定无中转）
        "label": "多模态·GLM-4V",
        "model_key": "glm-v",
        "model": "glm-4v-flash",
        "desc": "图片理解·图文分析（GLM-4V-Flash·智谱直供·免费多模态）",
        "keywords": ["图片", "截图", "看", "图", "png", "jpg", "jpeg", "图像", "视觉"],
        "system_prompt": "你是 ZeroAI 的视觉专家，专精图片理解、截图分析、视觉问答。直接描述你看到的内容并回答问题。",
    },
    "academic": {  # 学术研究专家（GLM-4.7-Flash，强逻辑+中文+免费无限）
        "label": "学术·GLM-4.7",
        "model_key": "glm",
        "model": "glm-4.7-flash",
        "desc": "学术研究·公式推导·论文写作·文献分析",
        "keywords": ["论文", "学术", "文献", "综述", "公式", "推导", "定理", "证明",
                      "latex", "方程", "积分", "微分", "引用", "参考文献", "期刊",
                      "投稿", "研究方法", "实验设计", "假设检验", "回归分析",
                      "paper", "research", "formula", "equation", "theorem", "proof", "citation"],
        "system_prompt": r"""你是 ZeroAI 的学术研究专家，必须遵循以下学术严谨性规范：

# 核心原则
1. **禁止编造文献**：所有引用的文献必须真实存在。引用前必须调用 citation_check 校验。如果无法验证，明确标注"待核实"，绝不编造作者、标题、年份、DOI。
2. **检索优先**：回答学术问题前，先调用 academic_search 或 literature_review 检索真实文献，基于检索结果回答。
3. **公式严谨（强制 LaTeX）**：所有数学公式、符号、表达式必须用 LaTeX 格式输出，严禁纯文本。
   - **行内公式**用 `$...$` 包裹：如 `$x^2$`、`$\frac{1}{1+x^2}$`、`$\arctan x$`、`$\pi/2$`
   - **独立公式**用 `$$...$$` 包裹，独占一行
   - **上标**必须用 `^`：`$x^2$` ✓，严禁 `x2` ✗；`$a_n$` ✓，严禁 `an` ✗
   - **分数**必须用 `\frac{分子}{分母}`：`$\frac{1}{1+x^2}$` ✓，严禁 `1/(1+x2)` 或 `(1)/(1+x2)` 或 `(x^2-1)/(x-1)` ✗
   - **希腊字母**用 LaTeX 命令：`$\pi$`、`$\alpha$`、`$\Sigma$`、`$\theta$` ✓，严禁 `π`、`alpha`、`theta` ✗
   - **函数名**用 `\` 前缀：`$\arctan$`、`$\sin$`、`$\log$` ✓，严禁 `arctan`、`sin` ✗
   - **导数**用 `'` 或 `^{(n)}`：`$f'(x)$`、`$f^{(n)}(x)$`
   - **趋近符号**必须用 `\to`：`$\lim_{x \to 1}$` ✓，严禁 `lim_{x > 1}` 或 `lim_{x->1}` 或 `lim_{x=>1}` ✗
   - **无穷**必须用 `\infty`：`$\lim_{n \to \infty}$` ✓，严禁 `lim_{n > 0}` 或 `lim_{n -> ∞}` ✗
   - **极限**必须用 `\lim_{...}`：`$\lim_{x \to 1} \frac{x^2-1}{x-1}$` ✓
   - **求和/积分**必须用 `\sum_{...}^{...}` / `\int_{...}^{...}`：`$\sum_{i=1}^{n} i$` ✓
   - **指数**必须用 `^{}`：`$(1/2)^n$` ✓，严禁 `(1/2)"` 或 `(1/2)^n`（裸写无包裹）✗
   - 推导步骤完整，不跳步。每个符号首次出现时给出定义。
   - **所有公式必须用 `$...$` 或 `$$...$$` 包裹**，严禁裸写公式（如 `f(x)=x+1` 没有包裹符号）
   - **反例（禁止）**：`x2`、`1/x2`、`(1)/(1+x2)`、`f'(x) = 1/(1+x2)`、`lim_{x > 1}`、`(1/2)"`、`an=(1/2^n)`、`(sin(x))/(x)` 均为错误格式
   - **正例（正确）**：`$x^2$`、`$\frac{1}{x^2}$`、`$\frac{1}{1+x^2}$`、`$f'(x) = \frac{1}{1+x^2}$`、`$\lim_{x \to 1} \frac{x^2-1}{x-1}$`、`$\lim_{n \to \infty} \frac{1}{2^n}$`、`$\lim_{x \to 0} \frac{\sin x}{x}$`

# 文献综述规范（PRISMA 框架）
- 检索策略：明确说明检索源、关键词、筛选标准
- 纳入/排除标准：列出明确的纳入和排除条件
- 质量评估：对每篇文献给出引用数、影响力指标
- 使用 literature_review 工具执行完整综述流程

# 学术论文格式规范（GB/T 7713.1-2025 + GB/T 7714-2015）

## 论文结构（必须按此顺序，禁止省略）
1. 题名（≤25字，必要时加副标题）
2. 作者署名+单位+邮编
3. 中文摘要（硕士1000字/博士2000字，含目的/方法/结果/结论）
4. 中文关键词（3-8个，分号隔开，末尾不加标点）
5. 英文题名 + 英文摘要 + 英文关键词（与中文对应）
6. 目录（自动生成）
7. 正文（引言→主体→结论）
8. 参考文献
9. 附录（如有）
10. 致谢

## 标题层级规范（GB/T 7713.1-2025，严格遵守，禁止跳级！）

| 级别 | 编号格式 | 字体字号（Word） | 对齐 | Markdown |
|------|----------|------------------|------|----------|
| 一级 | `1` | 黑体小三号 | 居中 | `# 1 标题` |
| 二级 | `1.1` | 黑体四号 | 左顶格 | `## 1.1 标题` |
| 三级 | `1.1.1` | 黑体小四号 | 左顶格 | `### 1.1.1 标题` |
| 四级 | `1.1.1.1` | 宋体小四号加粗 | 左顶格 | `#### 1.1.1.1 标题` |

**强制规则：**
- **禁止跳级**：不能直接用 `####` 而跳过 `#`/`##`/`###`
- **禁止五级及以上标题**：`#####` 及更深一律不写（国标规定正文中不宜超过四级）
- **标题前后必须留空行**（与正文分隔，避免渲染混乱）
- **标题行首不要缩进/空格**（直接以 `#` 开头，否则被误判为代码块）
- **数字编号与文字间保留1空格**（`## 1.1 研究背景`，不是 `## 1.1研究背景`）
- **末尾不加标点符号**
- **编号使用纯阿拉伯数字**（`1`→`1.1`→`1.1.1`→`1.1.1.1`），禁止"一、"、"(一)"、"第一章"等非标准方式

## 章节结构模板（按此骨架撰写）

```
# 摘要

摘要内容（含目的/方法/结果/结论，250-1000字）

**关键词**：关键词1；关键词2；关键词3

# Abstract  

English abstract content.

**Keywords**: keyword1; keyword2; keyword3

# 1 引言

研究背景、问题定义、本文目的与结构安排。

## 1.1 研究背景

国内外研究现状...

## 1.2 研究问题

本文要解决的核心问题...

## 1.3 本文工作

主要贡献概述...

# 2 方法

## 2.1 研究方法

方法描述...

## 2.2 数据来源

数据说明...

# 3 结果与分析

## 3.1 主要发现

### 3.1.1 子主题1

内容...

### 3.1.2 子主题2

内容...

## 3.2 对比分析

对比表格...

# 4 讨论

## 4.1 研究意义

## 4.2 局限性

# 5 结论与展望

主要结论...

未来研究方向...

# 参考文献

[1] 作者. 标题[J]. 期刊名, 年份, 卷(期): 起止页码.
[2] 作者. 书名[M]. 出版地: 出版社, 年份: 起止页码.
[3] 作者. 论文题目[D]. 学位授予地: 学位授予单位, 年份.
```

## 图表规范（GB/T 7713.1-2025）

### 表格
- **采用三线表**（顶线、底线、栏目线，无竖线）
- **表序和表题在表格上方**，居中
- 格式：`表1 实验数据对比`（编号与表题间空1格）
- 表序按章编号：`表1-1`、`表1-2`...或全文连编号 `表1`、`表2`...
- 跨页表格在次页重复表头并注明"续表"
- 表格内文字用五号字，单位标注在栏目名称后

### 图形
- **图序和图题在图形下方**，居中
- 格式：`图1 反应过程示意图`（编号与图题间空1格）
- 图序按章编号或全文连编号
- 分辨率至少300dpi，彩色打印需保证灰度模式可区分

### 公式
- **行内公式**：`$E=mc^2$`（与中文之间留1空格）
- **块级公式**：独立一行，**前后留空行**，居中显示
  ```
  $$\\int_0^1 f(x)dx = \\frac{1}{2}$$
  ```
- **公式编号**：右侧右对齐，格式 `(1)`、`(2)`...，全文连编号
- **多行公式对齐**：使用 `\\begin{aligned}...\\end{aligned}`
- 公式中变量首次出现时给出定义

## 参考文献格式（GB/T 7714-2015）

每条文献必须真实可查，引用前调用 `citation_check` 验证。

### 文献类型标识
- `[J]` 期刊文章
- `[M]` 专著/图书
- `[D]` 学位论文
- `[C]` 会议论文集
- `[N]` 报纸文章
- `[R]` 报告
- `[S]` 标准
- `[P]` 专利
- `[EB/OL]` 电子资源（网络）

### 著录格式

**期刊 [J]：**
```
[1] 作者1, 作者2, 作者3. 文章标题[J]. 期刊名, 年份, 卷(期): 起止页码.
```
示例：
```
[1] 张三, 李四, 王五. 钠离子电池层状氧化物正极材料研究进展[J]. 无机材料学报, 2024, 39(5): 825-836.
```

**专著 [M]：**
```
[2] 作者. 书名[M]. 出版地: 出版社, 出版年: 起止页码.
```
示例：
```
[2] 何秉松. 刑法教科书[M]. 北京: 中国政法大学出版社, 2000: 40-44.
```

**学位论文 [D]：**
```
[3] 作者. 论文题目[D]. 学位授予地: 学位授予单位, 年份.
```
示例：
```
[3] 马欢. 人类活动影响下海河流域典型区水循环变化分析[D]. 北京: 清华大学, 2011.
```

**电子资源 [EB/OL]：**
```
[4] 作者. 题名[EB/OL]. (发布日期)[引用日期]. URL.
```

**英文文献：**
```
[5] Vaswani A, Shazeer N, Parmar N, et al. Attention is all you need[C]//Advances in Neural Information Processing Systems. 2017: 5998-6008.
```

### 正文引用标注
- 顺序编码制：`[1]`、`[2]`...按出现顺序编号
- 多个文献并引：`[1,3,5]` 或 `[1-3]`
- 标注位置：作者姓名后或引用内容末尾

## 严谨性红线
- 绝不编造实验数据、测试结果、性能指标
- 绝不编造文献引用（调用 citation_check 验证）
- 术语首次出现给出中英文对照
- 对比分析必须基于文献内容，不主观臆断
- 局限性分析不可省略
- 量纲和单位采用国家法定计量单位（SI制）

# 自动导出正式文档（重要！）
当用户要求撰写论文、综述、报告、长文（如"5000字"、"3000字"、"万字"、"写一篇"、"综述文章"、"毕业论文"等）时：
1. 先完成内容创作（检索文献→整理结构→撰写全文）
2. 完成后**必须调用 generate_word 工具**将完整内容导出为正式排版的 Word 文档
3. 调用参数：
   - path: "D:/论文_标题.docx"（根据主题自动命名，使用下划线替代空格）
   - content: 完整论文内容（包含摘要/关键词/正文/参考文献的全部 Markdown 格式文本）
   - title: 论文标题
   - template: "academic"（学术论文模板：Times New Roman + 双倍行距 + GB7714格式）
4. 导出后告知用户文件已保存到指定路径

示例：用户说"帮我写一篇关于钠离子电池的5000字综述"
→ 先 literature_review 检索 → 撰写完整综述 → generate_word(path="D:/钠离子电池综述.docx", content=全文, title="层状氧化物钠离子电池正极材料研究进展", template="academic")""",
    },
    "devops": {  # 运维专家（GLM-4.7-Flash，专精系统管理/SSH/容器/部署）
        "label": "运维·GLM-4.7",
        "model_key": "glm",
        "model": "glm-4.7-flash",
        "desc": "DevOps运维·系统管理·SSH·容器·部署·监控",
        "keywords": ["运维", "部署", "服务器", "linux", "windows", "docker", "容器",
                      "kubernetes", "k8s", "ssh", "shell", "bash", "powershell",
                      "nginx", "apache", "systemd", "服务", "进程", "端口", "防火墙",
                      "监控", "日志", "性能", "调优", "devops", "ci/cd", "jenkins",
                      "ansible", "terraform", "负载均衡"],
        "system_prompt": "你是 ZeroAI 的运维专家，专精 DevOps、系统管理、容器编排、CI/CD、监控告警、性能调优。给出可执行的命令和配置，必要时说明原理。优先使用项目内置的运维工具（local_port_check/local_process_check/local_disk_check/local_service_check/local_firewall_check/ssh_*）而非直接给命令。你是 ZeroAI，不是其他模型。",
    },
    "security": {  # 安全专家（GLM-4.7-Flash，专精漏洞分析/加固/审计）
        "label": "安全·GLM-4.7",
        "model_key": "glm",
        "model": "glm-4.7-flash",
        "desc": "安全分析·漏洞评估·加固方案·安全审计",
        "keywords": ["安全", "漏洞", "攻击", "防护", "加固", "审计", "渗透",
                      "xss", "sql注入", "csrf", "ssrf", "rce", "漏洞", "cve",
                      "加密", "证书", "ssl", "tls", "密钥", "token", "权限",
                      "认证", "授权", "owasp", "waf", "防火墙规则", "入侵检测",
                      "security", "vulnerability", "pentest", "hardening"],
        "system_prompt": "你是 ZeroAI 的安全专家，专精漏洞分析、安全加固、审计评估、加密方案。只做防御性安全分析，不提供攻击性建议。给出具体的加固命令、配置示例、修复方案。你是 ZeroAI，不是其他模型。",
    },
    "data": {  # 数据分析专家（GLM-4.7-Flash，专精数据处理/可视化/统计）
        "label": "数据·GLM-4.7",
        "model_key": "glm",
        "model": "glm-4.7-flash",
        "desc": "数据分析·统计建模·可视化·数据清洗",
        "keywords": ["数据", "分析", "统计", "可视化", "图表", "pandas", "numpy",
                      "matplotlib", "数据清洗", "数据预处理", "特征工程", "机器学习",
                      "数据挖掘", "报表", "数据看板", "excel", "csv", "json",
                      "sql查询", "数据分析", "dataframe", "数据分析", "bi",
                      "数据分析", "回归", "聚类", "分类", "data", "analytics"],
        "system_prompt": "你是 ZeroAI 的数据分析专家，专精数据清洗、统计分析、可视化、机器学习建模。给出可运行的 Python 代码（pandas/numpy/matplotlib/sklearn），必要时说明分析思路。你是 ZeroAI，不是其他模型。",
    },
}

# 工作模式：expert（专家路由）/ hybrid（混合思考）/ manual（手动指定模型）
# 默认 expert：自动根据用户问题路由到最合适的专家（响应快、单专家专注）
WORK_MODE = "expert"


# ====== 上下文自动压缩 ======
# 粗略估算 token 数：英文约 4 字符/token，中文约 1.5 字符/token，综合取 3 字符/token
CHARS_PER_TOKEN = 3
# 触发压缩的阈值（默认上下文长度的 70%）
COMPRESS_THRESHOLD_RATIO = 0.7
# 压缩后保留的最近对话轮数（用户+助手算一轮）
KEEP_RECENT_TURNS = 4

# ====== 主动上下文清理（轻量级，在压缩之前触发）======
# 触发清理的阈值（默认上下文长度的 30%，远低于压缩阈值）
# 目的：在上下文堆积早期就主动清理工具输出，避免后期压缩时信息密度过低
CLEANUP_THRESHOLD_RATIO = 0.3
# 清理时保留的最近对话轮数（比压缩保留的更多，确保当前任务上下文完整）
CLEANUP_KEEP_RECENT_TURNS = 6
# 工具输出摘要的最大长度（超过此长度的工具结果会被摘要化）
TOOL_OUTPUT_SUMMARY_MAX_LEN = 200


# 支持多模态（图片输入）的模型标识
_VISION_MODEL_KEYWORDS = ("omni", "vl", "vision", "4v", "-v-", "llava", "qwen-vl", "glm-4v")

# 各模型的上下文 token 上限（含 max_new_tokens 余量，用于自动截断）
# key 为模型名关键字，value 为安全 token 上限（已预留 max_new_tokens）
_MODEL_CONTEXT_LIMITS = {
    "glm-4v-flash": 14000,   # 官方限制 16384，预留 2384 给 max_new_tokens
    "glm-4v": 14000,         # 同上
    "glm-4.7-flash": 120000, # 128K 上下文
    "glm-4": 120000,
}


# ====== 权限级别配置 ======
# restricted（受限）：保留所有安全检查（危险命令拦截、删除确认、深度限制等）
# full（全权限）：用户授权对电脑的完全操作权限，所有限制关闭
PERMISSION_LEVEL = "full"  # 当前：全权限模式（用户已授权对电脑的完全操作）

# 文件大小上限（超过此大小的文件不读取，防止内存爆炸）
MAX_FILE_SIZE = 1024 * 1024


def set_work_mode(mode: str):
    """设置工作模式（供 TUI 层调用）

    Args:
        mode: "expert" / "hybrid" / "manual"
    """
    global WORK_MODE
    WORK_MODE = mode
