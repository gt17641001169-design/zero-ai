# 更新日志

本文件记录 ZeroAI 项目的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.1.3] - 2026-07-28

### 新增
- **模块化架构**：新增 `zeroai` 包，将原 `tui_agent.py`（14748 行）拆分为三层：
  - `zeroai/core/`：核心层（8 个子模块：paths/runtime/secrets/constants/expert_route/context_compress/model_manager/response_utils）
  - `zeroai/tools/`：工具层（10 个子模块，56 个工具，`registry.py` 聚合 TOOLS schema 与 TOOL_MAP）
  - `zeroai/tui/`：TUI 包装层（7 个子模块：colors/markdown/identity/widgets/screens/app/icons）
- **统一入口**：新增 `zeroai/main.py` 与 `zeroai/__main__.py`，支持 `python -m zeroai`
- **版本号查询**：`python -m zeroai --version` 显示版本号
- **工具搜索**：`zeroai.tools.file_manager.search_files` 正则搜索文件内容
- **架构迁移说明**：`tui_agent.py` 顶部添加详细的架构迁移文档与弃用计划
- **LICENSE**：新增专有软件许可证
- **AUTHORS**：新增作者列表
- **CHANGELOG.md**：新增更新日志（本文件）
- **ReAct Agent Loop**（阶段 1）：思维链可视化、Plan-and-Execute 规划、Reflexion 自反思、并行工具调用、工具结果摘要
- **向量记忆与 RAG**（阶段 2）：GLM embedding-3 集成、混合检索（向量+BM25）、对话历史向量化、记忆衰减、文件背景监视
- **MCP 协议支持**（阶段 3）：JSON-RPC 2.0、stdio/SSE 双传输、自动工具注册、58 工具暴露、Claude Desktop 配置示例
- **C/Zig 加速层**（阶段 D）：三层降级（Zig→C→Python）、跨平台构建脚本、ABI 一致性测试、ctypes 加载、多层路径搜索、诊断函数
- **工具调用解析器**：`zeroai/core/tool_call_parser.py` 从 tui_agent.py 抽取 `_parse_tool_call_xml`、`_split_csv_args`、`needs_tool_calls`，独立可测试
- **Markdown 聚合模块**：`zeroai/tui/markdown.py` 聚合 6 个渲染函数（render_markdown/_safe_markdown/_normalize_markdown_for_academic/render_latex_in_text/_latex_to_unicode/render_image_preview）
- **MCP Claude Desktop 配置**：`zeroai/mcp/examples/claude_desktop_config.json` 提供即用配置
- **跨平台构建脚本**：`zeroai-tui/scripts/build_extensions.py` 支持 Windows/macOS/Linux

### 变更
- **入口点**：`pyproject.toml` 的 `project.scripts.zeroai` 由 `tui_agent:main` 改为 `zeroai.main:main`
- **包发现**：`pyproject.toml` 的 `packages.find` 包含 `zeroai*` 全部子包
- **版本号**：1.1.2 → 1.1.3
- **`.gitignore`**：新增 `zeroai-tui/.zig-cache/`、`zeroai-tui/zig-out/`、Zig 共享库与 C 扩展产物的排除规则
- **tui_agent.py 切换块扩展**：新增 `tool_call_parser` 切换块，将 `_parse_tool_call_xml`、`_split_csv_args`、`_needs_tool_calls` 切换到 `zeroai.core.tool_call_parser` 实现

### 内部调用切换
- **core 层切换**：`tui_agent.py` 通过"切换块"（`_ZEROAI_IMPL_ACTIVE`）将 38+ 个 core 层符号
  的实际调用切换到 `zeroai.core.*` 实现，原函数定义保留作为备份
- **tools 层切换**：56 个工具函数的实际调用切换到 `zeroai.tools.*` 实现
- **TOOLS/TOOL_MAP 切换**：`tui_agent.TOOLS` 与 `TOOL_MAP` 指向 `zeroai.tools.registry` 的同一对象
- **tool_call_parser 切换**（阶段 D.4）：`_parse_tool_call_xml` / `_split_csv_args` / `_needs_tool_calls` 切换到 `zeroai.core.tool_call_parser` 实现
- **回退机制**：导入失败时自动回退到 `tui_agent.py` 本地实现，`_ZEROAI_IMPL_ACTIVE=False`

### 安全
- **Zig 构建产物不入库**：`.gitignore` 排除 `zig_render.dll`、`.zig-cache/`、`zig-out/`，避免污染仓库

### 弃用
- **`tui_agent.py` 直接运行**：添加 `DeprecationWarning`，推荐改用 `python -m zeroai`
  （本入口在 v2.0 前仍可用，向后兼容）

### 测试
- 新增 `test_phase3_regression.py`：阶段3 切换块的 8 项回归测试
- 新增 `test_v1_1_3_release.py`：v1.1.3 发布的 10 项集成测试
- 新增 `test_mcp_integration.py`：MCP 端到端 8 项测试（C.1-C.4 全覆盖）
- 新增 `test_react_agent.py`：ReAct Agent + 向量记忆 11 项测试
- 新增 `test_tool_call_xml.py`：工具调用 XML 解析 4 项测试
- 新增 `test_tools_verification.py`：58 个工具可调用性 + 签名匹配验证
- 新增 `test_markdown_module.py`：Markdown 聚合模块 10 项测试
- zeroai-tui 测试套件：ABI 一致性 10 项测试全部通过

### 阶段 CDE 深入完成（2026-07-28）
- **阶段 C（MCP 接入验证）**：
  - C.1 预设依赖检测、C.2 Claude Desktop 配置、C.3 端到端 MCP Server、C.4 工具完整性
  - 8/8 测试通过，ZeroAI MCP Server 可被 Claude Desktop 等外部客户端调用
- **阶段 D（工程化与 C/Zig 加速层）**：
  - D.1 工具去重：file_ops.py 类版工具委托到 file_manager.py 函数版实现
  - D.2 voice 工具注册：speak_tts / listen_asr 注册到 TOOL_MAP（工具数 56→58）
  - D.3 死代码清理：system_check.py 移除 14 行死代码（已备份）
  - D.4 tui_agent.py 模块化拆分：tool_call_parser.py 抽取、markdown.py 聚合完善
  - Zig 库构建成功：`zeroai_tui/zig_render.dll`（HAS_ZIG_RENDERER=True）
  - ABI 一致性验证：StyleStruct 8 字节、字段偏移量、颜色映射、大缓冲区 stress
- **阶段 E（工程化与发布）**：
  - 版本号一致性：pyproject.toml / zeroai/__init__.py / README.md badge 全部 1.1.3
  - README.md 新增 4 个章节：ReAct Agent Loop、向量记忆与 RAG、MCP 协议支持、C/Zig 加速层
  - CHANGELOG.md 完整记录阶段 1-3 与 CDE 深入完成工作

---

## [1.1.2] - 2026-07-25

### 变更
- 代理服务器 IP 安全加固（Token 归属、暴力破解防护、HTTPS、审计日志脱敏）

---

## [1.1.1] - 2026-07-20

### 变更
- SSH 跨平台运维（Linux + Windows Server 自动适配）

---

## [1.1.0] - 2026-07-15

### 新增
- 多专家协同架构（7 位专家）
- SSH 远程部署工具集（7 个工具）
- AI 远程运维工具集（8 个语义化工具）
- 本地运维工具集（4 个跨平台工具）
- 学术研究工具（Semantic Scholar / arXiv / LaTeX 公式渲染）
- 国标文档生成（Word / Excel / PDF）
- 离线语音识别（SenseVoice）
- 代理服务器（API Key 零泄露）
