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

### 变更
- **入口点**：`pyproject.toml` 的 `project.scripts.zeroai` 由 `tui_agent:main` 改为 `zeroai.main:main`
- **包发现**：`pyproject.toml` 的 `packages.find` 包含 `zeroai*` 全部子包
- **版本号**：1.1.2 → 1.1.3
- **`.gitignore`**：新增 `zeroai-tui/.zig-cache/`、`zeroai-tui/zig-out/`、Zig 共享库与 C 扩展产物的排除规则

### 内部调用切换
- **core 层切换**：`tui_agent.py` 通过"切换块"（`_ZEROAI_IMPL_ACTIVE`）将 38+ 个 core 层符号
  的实际调用切换到 `zeroai.core.*` 实现，原函数定义保留作为备份
- **tools 层切换**：56 个工具函数的实际调用切换到 `zeroai.tools.*` 实现
- **TOOLS/TOOL_MAP 切换**：`tui_agent.TOOLS` 与 `TOOL_MAP` 指向 `zeroai.tools.registry` 的同一对象
- **回退机制**：导入失败时自动回退到 `tui_agent.py` 本地实现，`_ZEROAI_IMPL_ACTIVE=False`

### 安全
- **Zig 构建产物不入库**：`.gitignore` 排除 `zig_render.dll`、`.zig-cache/`、`zig-out/`，避免污染仓库

### 弃用
- **`tui_agent.py` 直接运行**：添加 `DeprecationWarning`，推荐改用 `python -m zeroai`
  （本入口在 v2.0 前仍可用，向后兼容）

### 测试
- 新增 `test_phase3_regression.py`：阶段3 切换块的 8 项回归测试
- 新增 `test_v1_1_3_release.py`：v1.1.3 发布的 10 项集成测试
- zeroai-tui 测试套件：30 项测试全部通过

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
