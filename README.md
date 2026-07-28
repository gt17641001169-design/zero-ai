<div align="center">

# ZeroAI

### 面向科研与工程的终端 AI 协作平台

**多专家协同 · 学术文献检索 · 国标文档生成 · 安全审计 · SSH 跨平台运维 · 本地运维**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-green.svg)]()
[![License](https://img.shields.io/badge/License-Proprietary-orange.svg)](LICENSE)
[![PyPI](https://img.shields.io/badge/PyPI-zero--ai--cli-1.1.3-blue.svg)](https://pypi.org/project/zero-ai-cli/1.1.3/)
[![GitHub](https://img.shields.io/badge/GitHub-zero--ai-black.svg)](https://github.com/gt17641001169-design/zero-ai)

</div>

---

## 摘要

ZeroAI 是一个面向科研工作者与开发者的终端 AI 协作平台。系统采用多专家协同架构，将任务规划、代码生成、深度推理、学术写作、文献检索、文档生成、安全审计、远程运维等能力集成于单一终端环境，旨在降低科研与工程协作中的工具切换成本，提升研究产出效率。

系统针对科研场景进行了针对性设计：集成 Semantic Scholar 学术数据库（2 亿+ 论文），支持按引用数、影响力、年份智能筛选；内置 LaTeX 公式渲染引擎，支持分数、根号、矩阵、极限、求和、积分等学术公式的 Unicode 化与 PDF 高清图片输出；按 GB/T 7713.1-2025 国标格式生成 Word/PDF 学术文档；离线语音识别引擎保障科研数据隐私；代理服务器架构实现 API Key 零泄露，支持团队安全协作。

---

## 科研价值

### 1. 学术文献检索与综述辅助

集成 Semantic Scholar 学术数据库（覆盖 2 亿+ peer-reviewed 论文），支持：
- 按关键词、作者、DOI 检索文献
- 按引用数、影响力、发表年份智能排序
- 自动生成文献综述初稿，辅助研究者快速了解领域全貌
- 免费无 API Key 限制，适合科研经费有限的课题组

### 2. 学术公式推导与渲染

内置 LaTeX 公式渲染引擎，支持：
- 行内公式 `$...$` 与独立公式 `$$...$$` 双模式
- 分数、根号、上下标、希腊字母、矩阵、极限、求和、积分、偏导数等学术符号
- 独立公式通过 matplotlib mathtext 渲染为高清图片，可直接嵌入 PDF/Word
- Unicode 化输出，兼容终端显示与文档排版

### 3. 国标学术文档生成

按 GB/T 7713.1-2025《科学技术报告、学位论文和学术论文的编写格式》生成：
- 四级标题层级结构（`#` ~ `####`）
- 自动参考文献格式化
- 学术公式、表格、图片混排
- 输出 .docx / .pdf 双格式，符合学术出版规范

### 4. 多专家协同研究

7 位专家协同处理同一研究问题，项目经理统一调度：
- 学术研究专家：负责文献调研、公式推导、论文写作
- 推理专家：负责数学证明、逻辑分析、复杂度分析
- 编程专家：负责算法实现、实验代码、数据处理
- 项目经理：负责任务分解、结果汇总、多模态分析
- 适用于跨学科研究场景（如计算语言学、生物信息学、计算社会科学）

### 5. 离线语音识别与数据隐私

- 基于 SenseVoice（阿里达摩院）的离线语音识别引擎
- 中英日韩粤 5 语言支持，适用于国际协作
- 完全离线运行，科研数据不出本机，符合涉密科研项目数据安全要求
- 无需 API Key，无云端调用，无数据泄露风险

### 6. 团队协作与 API Key 隔离

代理服务器架构实现 API Key 零泄露：
- 真实 API Key 仅存于服务器端 `.env` 文件
- 客户端仅持有访问 Token，与上游 Key 完全分离
- 支持多用户 Token 分配，便于课题组多成员协作
- 限流与审计日志，防止滥用与可追溯

### 7. 科研代码安全审计

针对科研代码（尤其是数据处理、统计分析代码）提供：
- 硬编码密钥扫描（防止数据集访问凭据泄露）
- 路径遍历检测（防止实验数据误删）
- 依赖包已知漏洞检查
- 非侵入式扫描，不进行渗透测试

---

## 系统架构

### 多专家协同架构

| 专家 | 职责 | 适用场景 |
|------|------|---------|
| 项目经理 | 任务分析、调度、多模态 | 跨学科问题分解、图文分析 |
| 编程 | 代码生成、调试、重构 | 算法实现、实验代码 |
| 推理 | 深度推理、数学、逻辑 | 数学证明、复杂度分析 |
| 通用知识 | 通用问答、翻译、百科 | 跨语言文献翻译、概念查询 |
| 中文写作 | 中文写作、文案、报告 | 中文学术写作、研究报告 |
| 多模态 | 图片理解、图文分析 | 图表分析、实验结果可视化 |
| 学术研究 | 学术研究、公式推导、论文写作 | 文献综述、论文撰写 |

### 自动路由机制

根据问题关键词自动分配至最合适专家，例如：
- "证明..." → 推理专家
- "实现..." → 编程专家
- "论文..." → 学术研究专家
- "翻译..." → 通用知识专家

### 混合思考模式

多专家协作处理同一问题，项目经理汇总各专家结论，适用于复杂研究问题（如"设计实验验证假设并分析统计显著性"）。

---

## 核心功能

### SSH 远程部署（7 个工具）

- 多服务器并行连接，通过 `conn_id` 区分，支持密码/密钥认证
- 远程命令执行，危险命令（rm -rf /、mkfs、dd 等 11 类）二次确认
- SFTP 文件传输，上传/下载文件，自动设置权限
- 一键自动化部署 `ssh_deploy`（pre_check → mkdir → upload → install → restart → health_check → post_cmds）
- 审计日志（最多 200 条），可追溯
- 主机地址校验、危险命令黑名单、内网IP可选阻断、输出截断保护

### AI 远程运维（8 个语义化工具，跨平台）

将"AI 拼命令"升级为"AI 调用语义化工具"，减少幻觉、统一错误处理、自动分析结果。8 个工具全部支持 **Linux + Windows Server 跨平台自动适配**：

| 工具 | 功能 |
|------|------|
| `ssh_service_manage` | systemd 封装（status/start/stop/restart/enable） |
| `ssh_log_view` | journalctl 封装，自动统计错误密度 |
| `ssh_process_check` | 按 CPU/内存排序 Top N |
| `ssh_disk_analyze` | df + du Top10，自动标注危急/警告 |
| `ssh_network_diag` | 端口/连接/ping/统计 |
| `ssh_docker_manage` | 容器/镜像/日志/资源 |
| `ssh_firewall_manage` | 自动识别 ufw/firewalld/iptables |
| `ssh_health_check` | 综合报告 + AI 健康分析 + 异常项标注 |

### AI 运维决策链

- 模糊问题处理："服务器卡了" → 先体检 → 再深入 → 定位 → 给建议
- 明确故障排错："nginx 挂了" → 看 status → 若 failed → 查 error 日志 → 定位根因
- AI 主动分析：体检报告自动识别负载/磁盘/Swap/失败服务/错误日志异常项

### SSH 跨平台运维（Linux + Windows Server）

8 个 AI 远程运维工具全部支持**跨平台自动适配**，连接后自动检测远程操作系统，无需用户指定命令语法：

| 工具 | Linux 实现 | Windows 实现 |
|------|-----------|-------------|
| `ssh_service_manage` | `systemctl` | `sc.exe` / `Get-Service` |
| `ssh_log_view` | `journalctl` | `Get-WinEvent`（事件日志） |
| `ssh_process_check` | `ps aux` | `Get-Process` |
| `ssh_disk_analyze` | `df` + `du` | `Get-CimInstance` + `Get-ChildItem` Top10 |
| `ssh_network_diag` | `ss` / `netstat` | `Get-NetTCPConnection` |
| `ssh_docker_manage` | 原生 Docker CLI | Docker Desktop（`docker.exe`） |
| `ssh_firewall_manage` | `ufw` / `firewalld` / `iptables` | `netsh advfirewall` |
| `ssh_health_check` | 综合体检（自动检测 OS） | 综合体检（Windows Server 指标） |

**跨平台价值**：
- 同一套自然语言指令可管理 Linux 和 Windows 服务器："看 nginx 状态" 在两端都能正确执行
- 运维人员无需记忆两套命令语法，降低跨平台运维门槛
- 工具内部处理命令差异，AI 无需拼命令，减少幻觉

### 本地运维工具（4 个语义化工具，跨平台）

将常用的本地电脑运维操作封装为语义化工具，自动适配 Windows/Linux，**优先于 `run_command` 手拼命令调用**：

| 工具 | 功能 | 典型场景 |
|------|------|---------|
| `local_port_check` | 端口/网络检查 | "看看打开了哪些端口"、"80 端口被占了吗"、"ping 一下 192.168.1.1" |
| `local_process_check` | 进程查看/管理 | "电脑卡不卡"、"查 chrome 进程"、"结束 PID 1234" |
| `local_disk_check` | 磁盘空间分析 | "磁盘还剩多少"、"哪个目录占空间最大"、"C 盘满了" |
| `local_service_check` | 服务管理 | "查看运行的服务"、"MySQL 状态"、"重启 docker 服务" |

**安全设计**：
- 防注入白名单：进程名/服务名仅允许字母、数字、`.`、`_`、`-`，拒绝 `nginx; rm -rf /` 类注入
- 端口检查用 socket 连接探测，不依赖外部命令
- 危险操作（kill/stop）需明确参数

### 跨平台命令兼容性（run_command 自动翻译）

`run_command` 工具内置 **Linux ↔ Windows 命令翻译引擎**，用户可输入任意平台命令，系统自动适配当前操作系统：

```
用户在 Windows 上输入 'ls -la'      → 自动执行 'dir -la'
用户在 Windows 上输入 'cat file'    → 自动执行 'type file'
用户在 Windows 上输入 'rm -rf /tmp' → 自动执行 'rmdir /s /q /tmp'
用户在 Windows 上输入 'grep x file' → 自动执行 'findstr x file'
用户在 Windows 上输入 'ps aux'      → 自动执行 'tasklist aux'
```

**翻译特性**：
- **50+ 命令映射**：覆盖文件操作、网络、服务、进程、包管理等常用命令
- **最长匹配优先**：`rm -rf` 优先于 `rm` 匹配，避免误翻译
- **智能跳过**：原命令已是目标平台格式（如 `netstat -ano`）时自动跳过翻译，避免重复
- **翻译提示**：翻译后输出 `[跨平台] 已将 'ls' 翻译为 'dir'` 提示用户

### 语音对话

- 离线语音识别：SenseVoice（阿里达摩院），中英日韩粤 5 语言，无需 API Key
- 语音合成：Edge TTS，男女声切换、语速调节
- 实时字幕：对话模式下显示实时字幕
- 快捷操作：Ctrl+T 单次语音输入，Ctrl+D 持续对话模式

### 安全审计

- 漏洞扫描：SQL 注入、XSS、硬编码密钥、路径遍历等
- 依赖检查：扫描依赖包已知漏洞
- 配置审计：检查配置文件安全问题
- 非侵入式：仅扫描自身项目，不进行渗透测试

---

## 安装

### 方式一：pip 安装（推荐）

```bash
pip install zero-ai-cli
```

### 方式二：从源码安装

```bash
git clone https://github.com/gt17641001169-design/zero-ai.git
cd zero-ai-cli
pip install -e .
```

### 可选：安装语音功能

```bash
pip install zero-ai-cli[voice]
```

语音功能包含：sherpa-onnx（语音识别）、faster-whisper（备用识别）、av（音频处理）。

首次使用语音功能时，会自动从 HuggingFace 镜像下载 SenseVoice 模型（约 220MB），下载后离线运行。

---

## 使用

安装后在任意终端输入：

```bash
zeroai
```

或使用 Python 模块入口（推荐）：

```bash
python -m zeroai                    # 默认 Textual UI（推荐）
python -m zeroai --ui textual       # 显式指定 Textual UI
python -m zeroai --ui zeroai-tui    # C/Zig 加速 TUI
python -m zeroai --expert coder     # 直接指定专家
python -m zeroai --version          # 查看版本号
```

> **架构变更说明**：自 v1.1.3 起，项目从单文件 `tui_agent.py` 重构为模块化 `zeroai` 包。
> `python -m zeroai` 为推荐入口，`python tui_agent.py` 仍可用（向后兼容，已添加弃用提示）。

### 首次使用配置

**方式 A：直连模式（个人使用）**

1. 获取 GLM API Key（免费）：访问 https://open.bigmodel.cn/ 注册并创建 Key
2. 启动 ZeroAI 后按 `Ctrl+P` 打开设置面板
3. 填入 GLM API Key 并保存
4. 或设置环境变量：`ZEROAI_API_KEY_GLM=你的Key`

**方式 B：代理模式（团队协作，推荐）**

通过代理服务器访问 AI 模型，客户端零 API Key 泄露：

1. 部署代理服务器（见下文"代理服务器部署"章节）
2. 启动 ZeroAI 后按 `Ctrl+P` 打开设置面板
3. 在"代理服务器"段配置：
   - 代理地址：`http://<服务器IP>:8000/v1`
   - 访问 Token：由管理员分配
   - 代理模式：启用
4. 所有请求自动经代理转发，真实 Key 仅存于服务器端

### 命令列表

#### 基础命令

| 命令 | 说明 |
|------|------|
| `/帮助` | 显示帮助 |
| `/清屏` | 清空屏幕 |
| `/新对话` | 开始新对话 |
| `/退出` | 退出程序 |

#### 模式切换

| 命令 | 说明 |
|------|------|
| `/专家` | 切换到专家模式（自动路由） |
| `/混合` | 切换到混合思考（多专家协作） |
| `/手动` | 切换到手动模式（指定模型） |
| `/模型` | 查看当前模型和专家团队 |
| `/模型 glm` | 切换到智谱 GLM |
| `/模型 glm-v` | 切换到智谱 GLM-4V（多模态） |
| `/模型 openrouter` | 切换到 OpenRouter |
| `/模型 ollama` | 切换到 Ollama（本地模型） |

#### 语音交互

| 命令 | 说明 |
|------|------|
| `/语音` | 开启/关闭 AI 回复自动朗读 |
| `/对话` | 开启语音对话模式 |
| `/停止` | 停止语音对话模式 |
| `/女声` | 切换为女声（晓晓） |
| `/男声` | 切换为男声（云希） |
| `/语速 +10%` | 设置语速 |
| `Ctrl+T` | 单次语音输入 |
| `Ctrl+D` | 语音对话模式 |

#### 其他功能

| 命令 | 说明 |
|------|------|
| `/图片` | 粘贴剪贴板图片 |
| `/复制` | 复制最近回复 |
| `/安全` | 安全审计 |
| `/ssh` | 查看 SSH 远程部署 + AI 运维工具集（15 个工具） |
| `Ctrl+G` | 粘贴图片快捷键 |
| `Ctrl+N` | 新对话 |
| `Ctrl+P` | 设置面板 |
| `Ctrl+W` | 伴随模式 |
| `Ctrl+Y` | 复制 |

---

## 代理服务器部署（团队协作）

代理服务器实现 API Key 零泄露，适用于课题组、实验室、企业团队协作场景。

### 架构

```
客户端（zeroai）  ──Token 鉴权──>  代理服务器  ──真实Key──>  上游AI（GLM/OpenRouter）
                                    │
                                    ├─ 限流（30次/分钟/IP）
                                    ├─ 模型白名单
                                    ├─ 流式 SSE 透传
                                    └─ 审计日志
```

### 部署步骤

1. 上传 `zeroai-proxy/` 目录到服务器
2. 安装依赖：`pip install -r requirements.txt`
3. 配置 `.env`（从 `.env.example` 复制）：
   ```bash
   GLM_API_KEY=你的智谱Key
   OR_API_KEY=你的OpenRouter Key
   CLIENT_TOKENS=为每个成员生成的访问Token
   ALLOWED_MODELS=glm-4.7-flash,glm-4-flash,glm-4v-flash
   ```
4. 启动服务（Linux systemd / Windows NSSM / Docker 任选）
5. 防火墙放行 8000 端口（仅内网）
6. 客户端配置代理地址 + Token 即可使用

### 安全特性

| 特性 | 说明 |
|------|------|
| API Key 隔离 | 真实 Key 只在服务器 `.env`，客户端永远拿不到 |
| Token 鉴权 | 客户端用独立 Token，与上游 Key 完全分离 |
| 限流 | 每 IP 滑动窗口 30 次/分钟（可配置） |
| 模型白名单 | 防止客户端调用昂贵模型 |
| 流式透传 | 完整支持 SSE，流式输出不受影响 |
| OpenAI 兼容 | 客户端无需改造 SDK，只需改 base_url |
| 日志审计 | 记录 IP/Token/模型/状态，便于追溯 |

### IP 安全设计（v1.2.0 安全加固）

针对代理服务器在团队/内网部署场景下的安全威胁，v1.2.0 版本进行了系统性的 IP 与 Token 安全加固：

#### 1. Token 归属与生命周期管理

| 能力 | 说明 |
|------|------|
| Token 归属 | 每个 Token 绑定用户名、团队、备注，便于审计追溯 |
| 用量统计 | 自动记录调用次数、最后使用时间 |
| 过期时间 | 支持永久 Token 或指定过期时间（ISO 8601 格式） |
| 即时吊销 | 修改 `tokens.json` 后**热重载生效**，无需重启服务 |
| 状态恢复 | 已吊销的 Token 可恢复使用 |
| 统计重置 | 可重置 Token 的用量计数 |
| 管理端点 | `/admin/tokens` 查看、`/admin/revoke` 吊销（需 ADMIN_TOKEN） |

Token 文件格式（`tokens.json`）：
```json
{
  "abc123def456...": {
    "user": "张三",
    "team": "开发团队",
    "revoked": false,
    "expires": null,
    "usage_count": 0,
    "last_used": null,
    "created_at": "2026-07-25T10:00:00"
  }
}
```

#### 2. 暴力破解防护

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_FAILURES` | 5 | 同一 IP 连续失败 N 次触发封禁 |
| `BAN_MINUTES` | 30 | 封禁时长（分钟） |
| `BAN_WINDOW_MINUTES` | 10 | 失败计数窗口（分钟） |

- 同一 IP 在 10 分钟窗口内连续失败 5 次 → 自动封禁 30 分钟
- 验证成功后自动清除该 IP 的失败记录
- 封禁列表可通过 `/admin/banned` 查看（需 ADMIN_TOKEN）

#### 3. HTTPS 加密传输（自签证书）

- 生成自签证书：`python generate_cert.py`（基于 `cryptography` 库）
- 启用后 Token 加密传输，防中间人嗅探
- 客户端配置 `verify_ssl=false` 接受自签证书（内网部署场景）
- 证书文件（`cert.pem` / `cert.key`）通过 `.gitignore` 排除，不入版本库

#### 4. API 文档端点关闭

| 端点 | 状态 | 说明 |
|------|------|------|
| `/docs` | 关闭 | Swagger UI 不暴露 |
| `/redoc` | 关闭 | ReDoc 不暴露 |
| `/openapi.json` | 关闭 | OpenAPI schema 不泄露接口结构 |

防止攻击者通过 API 文档探测系统接口与参数。

#### 5. IP 脱敏审计日志

所有日志中的 IP 地址自动脱敏，仅保留前两段：
```
原 IP：192.168.10.66  →  日志：192.168.xxx.xxx
```
- 保护用户隐私，便于内部审计
- 封禁/解封日志同样脱敏

#### 6. 管理端点鉴权

`/admin/*` 端点需 `ADMIN_TOKEN` 鉴权（独立于客户端 Token）：
- `/admin/tokens`：列出所有 Token（脱敏）
- `/admin/revoke`：吊销指定 Token
- `/admin/reinstate`：恢复已吊销 Token
- `/admin/banned`：查看当前封禁 IP 列表
- `/admin/unban`：解封指定 IP

#### 7. .gitignore 安全排除

```gitignore
# 安全相关（证书和 Token 文件，绝不进 Git）
*.pem
*.key
*.crt
tokens.json
cert.pem
cert.key
*.bak.*
```

确保敏感文件不会误提交到版本库。

详细部署文档见 [zeroai-proxy/README.md](zeroai-proxy/README.md)。

---

## 系统要求

- Python >= 3.10
- 操作系统：Windows / macOS / Linux
- 网络：需访问智谱 GLM API（`open.bigmodel.cn`）或代理服务器
- 语音功能：需麦克风（仅语音对话模式）
- 多模态：支持 png/jpg/jpeg/gif/bmp/webp 格式图片

---

## 配置

### 配置文件位置

- Windows：`%USERPROFILE%\.zeroai\config.json`
- macOS/Linux：`~/.zeroai/config.json`

### 环境变量

| 环境变量 | 说明 |
|---------|------|
| `ZEROAI_API_KEY_GLM` | 智谱 GLM API Key（直连模式） |
| `ZEROAI_API_KEY_OPENROUTER` | OpenRouter API Key（直连模式） |
| `ZEROAI_HOME` | ZeroAI 资源目录（libs/models 所在位置） |

### 资源目录查找顺序

1. 脚本所在目录（开发模式）
2. `ZEROAI_HOME` 环境变量指定的目录
3. 用户主目录 `~/.zeroai/`（pip 安装模式）

---

## 技术栈

| 组件 | 技术 |
|------|------|
| UI 框架 | Textual TUI |
| AI 接口 | OpenAI SDK（兼容 GLM API） |
| SSH 远程 | asyncssh（纯 Python 异步 SSH） |
| 语音识别 | sherpa-onnx + SenseVoice（离线） |
| 语音合成 | Edge TTS |
| 文档生成 | python-docx + reportlab + matplotlib |
| 学术公式 | LaTeX → Unicode + matplotlib mathtext |
| 文献检索 | Semantic Scholar API |
| 代理服务 | FastAPI + httpx |

---

## 功能演示

### 多专家协作

```
用户：帮我写一个 Python 函数计算斐波那契数列，并分析时间复杂度

→ 项目经理·GLM-4V 分析任务
→ 编程·GLM-4.7 生成代码
→ 推理·内置 分析复杂度
→ 项目经理·GLM-4V 汇总结果
```

### 学术文献检索

```
用户：检索近三年关于 Transformer 加速的论文，按引用数排序

→ 学术研究专家调用 Semantic Scholar API
→ 返回 10 篇高引论文（标题/作者/年份/引用数/摘要）
→ 自动生成文献综述初稿
```

### 学术文档生成

```
用户：请生成一份关于机器学习的学术报告，Word 格式，包含公式

→ 学术研究·GLM-4.7 生成内容
→ LaTeX 公式渲染：$$E = mc^2$$ → 高清图片嵌入
→ 自动按 GB/T 7713.1-2025 格式排版
→ 保存为 .docx 文件
```

### SSH 远程部署

```
用户：连接到 192.168.10.22，用户 root，密码 xxx，把 D:/项目/myapp 部署到 /opt/myapp

→ ssh_connect 建立连接（conn_id=default）
→ ssh_deploy 一键部署：
  1. pre_check  → 检查磁盘空间/Python版本
  2. mkdir      → 创建 /opt/myapp 目录
  3. upload     → SFTP 上传项目文件
  4. install    → pip install -r requirements.txt
  5. restart    → systemctl restart myapp
  6. health_check → curl localhost:8080/health
  7. post_cmds  → 清理临时文件
→ 生成部署报告
```

### AI 远程运维

```
用户：服务器卡了，看看怎么回事

→ ssh_health_check 一键体检
  → 系统信息、CPU、内存、磁盘、网络、负载、失败服务、错误日志
  → AI 分析：发现 3 个问题
    1. 1分钟负载 5.2 偏高
    2. 磁盘使用率 92%（危急）
    3. 最近1小时有 15 条错误日志
  建议深入排查

用户：mysql 状态怎么样
→ ssh_service_manage(action=status, service=mysql)
→ 自动状态解读：服务运行中 / 服务未运行 / 异常退出

用户：查 nginx 的 error 日志
→ ssh_log_view(service=nginx, keyword=error)
→ 返回日志 + 自动统计：错误密度高，建议深入排查

用户：开放 8080 端口
→ ssh_firewall_manage(action=open, port=8080)
→ 自动识别防火墙类型（ufw/firewalld/iptables）并执行
```

---

## 开发

### 开发模式安装

```bash
git clone https://github.com/gt17641001169-design/zero-ai.git
cd zero-ai-cli
pip install -e .           # 主包（开发模式）
pip install -e ".[dev]"    # 开发依赖（build、pyinstaller）
pip install -e ".[voice]"  # 可选：语音依赖
```

开发模式下修改 `zeroai/` 包或 `tui_agent.py` 即时生效，无需重新安装。

### 构建

```bash
pip install build
python -m build
```

生成的包在 `dist/` 目录（`.whl` 与 `.tar.gz`）。

### 构建 C/Zig 加速层（可选）

```bash
cd zeroai-tui
python setup.py build_ext --inplace            # 同时构建 Zig 和 C 扩展
python setup.py build_ext --inplace --skip-zig # 仅构建 C 扩展（跳过 Zig）
```

加速层架构：Python → C → Zig（失败自动回退到 C 标量实现）。

### 运行测试

```bash
# 阶段3 切换块回归测试
python test_phase3_regression.py

# v1.1.3 发布集成测试
python test_v1_1_3_release.py

# C/Zig 加速层测试套件
python -m pytest zeroai-tui/test_zeroai_tui.py zeroai-tui/tests/ -v -p no:xonsh
```

### 项目结构

```
zero-ai-cli/
├── zeroai/                   # 模块化包（推荐入口，v1.1.3+）
│   ├── core/                 # 核心层（8 个子模块）
│   │   ├── paths.py          # 路径管理
│   │   ├── runtime.py        # 运行时缓存与中断控制
│   │   ├── secrets.py        # 密钥与配置持久化
│   │   ├── constants.py      # 常量与专家团队
│   │   ├── expert_route.py   # 专家路由（含 LRUCache）
│   │   ├── context_compress.py # 上下文压缩
│   │   ├── model_manager.py  # 模型管理
│   │   └── response_utils.py # 响应处理工具
│   ├── tools/                # 工具层（10 个子模块，56 个工具）
│   │   ├── file_manager.py   # 文件操作
│   │   ├── command_exec.py   # 命令执行
│   │   ├── network.py        # 网络操作
│   │   ├── system_check.py   # 系统检查
│   │   ├── security.py       # 安全审计
│   │   ├── doc_gen.py        # 文档生成
│   │   ├── academic.py       # 学术研究
│   │   ├── window_mgr.py     # 窗口管理
│   │   ├── ssh_ops.py        # SSH 远程运维
│   │   └── registry.py       # 工具注册中心（TOOLS + TOOL_MAP）
│   ├── tui/                  # TUI 包装层（7 个子模块）
│   │   ├── colors.py         # 配色常量
│   │   ├── markdown.py       # Markdown/LaTeX 渲染
│   │   ├── identity.py       # 身份泄露过滤
│   │   ├── widgets.py        # 自定义组件
│   │   ├── screens.py        # 模态对话框
│   │   ├── app.py            # ZeroAI 主应用类
│   │   └── icons.py          # 图标加载
│   ├── main.py               # 统一入口
│   └── __main__.py           # 模块入口（支持 python -m zeroai）
├── tui_agent.py              # 原始实现（保留备份，向后兼容，已弃用）
├── zeroai-tui/               # C/Zig 加速 TUI 框架
│   ├── zeroai_tui/           # TUI 组件包
│   │   ├── src/_renderer.c   # C 渲染核心（动态加载 Zig）
│   │   ├── src/_terminal.c   # C 终端控制
│   │   └── components.py     # TUI 组件框架
│   ├── src/zig_render.zig    # Zig 渲染加速
│   ├── build.zig             # Zig 构建脚本
│   ├── setup.py              # C/Zig 扩展构建
│   └── tests/                # 测试套件
├── zeroai-proxy/             # 代理服务器（API Key 保护）
│   ├── main.py               # FastAPI 代理主程序
│   ├── requirements.txt      # 依赖清单
│   ├── .env.example          # 配置模板
│   ├── Dockerfile            # Docker 部署
│   ├── docker-compose.yml
│   ├── start.sh              # systemd 部署脚本
│   └── README.md             # 部署文档
├── assets/icons/             # 图标资源
├── pyproject.toml            # 包配置
├── README.md                 # 说明文档
├── CHANGELOG.md              # 更新日志
├── CONTRIBUTING.md           # 贡献指南
├── LICENSE                   # 专有软件许可证
├── AUTHORS                   # 作者列表
├── install.bat               # Windows 一键安装脚本
└── libs/ models/             # 语音依赖（开发模式，不入库）
```

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 常见问题

### Q: 启动后提示"请配置 GLM API Key"？

A: 按 `Ctrl+P` 打开设置面板，填入智谱 GLM API Key。免费获取：https://open.bigmodel.cn/

### Q: 语音功能无法使用？

A:
1. 确认已安装语音依赖：`pip install zero-ai-cli[voice]`
2. 首次使用会自动下载模型（约 220MB）
3. 确认麦克风权限已开启

### Q: 提示 RateLimitError（限流）？

A: GLM 免费额度有限，系统会自动降级到其他模型。如频繁限流，可：
- 在智谱平台升级额度
- 配置 OpenRouter 作为备用
- 使用自己的 GLM API Key
- 部署代理服务器统一管理额度

### Q: 支持 macOS / Linux 吗？

A: 核心功能支持。语音功能在 macOS/Linux 上可能需要额外配置音频驱动。

### Q: SSH 远程运维怎么使用？

A:
1. 直接用自然语言告诉 AI："连接到 192.168.10.22，用户 root，密码 xxx"
2. AI 会自动调用 `ssh_connect` 建立连接
3. 之后可以这样说："看 nginx 状态"、"服务器卡了体检一下"、"查 mysql 错误日志"、"开放 8080 端口"、"重启 web 容器"
4. AI 会自动调用对应的语义化运维工具（`ssh_service_manage` / `ssh_health_check` / `ssh_log_view` / `ssh_firewall_manage` / `ssh_docker_manage` 等）
5. 输入 `/ssh` 查看完整的 15 个 SSH/运维工具列表

### Q: SSH 操作安全吗？

A: 设计了多重安全保障：
- **危险命令黑名单**：rm -rf /、mkfs、dd、shutdown 等 11 类必须 `confirm_dangerous=true` 二次确认
- **注入防护**：服务名/容器名白名单校验，拒绝 `nginx; rm -rf /` 这类命令注入
- **审计日志**：所有 SSH 操作自动记录（最多 200 条），可通过 `ssh_list` 查询
- **主机校验**：IP/域名格式校验，可选阻断内网 IP
- **输出截断**：命令输出超 8000 字符自动截断，防止刷屏

### Q: 一键部署 `ssh_deploy` 怎么用？

A: 直接告诉 AI 部署需求，AI 会自动构造 deploy_config：

```
把 D:/项目/myapp 部署到 192.168.10.22 的 /opt/myapp，
安装依赖 pip install -r requirements.txt，
重启命令 systemctl restart myapp，
健康检查 curl localhost:8080/health
```

AI 会自动执行 7 步骤并生成部署报告。

### Q: 代理服务器如何保护 API Key？

A: 代理服务器架构下：
- 真实 API Key 仅存于服务器端 `.env` 文件（不入 Git，不入客户端）
- 客户端仅持有访问 Token，与上游 Key 完全分离
- 客户端抓包只能看到 Token，无法获取真实 Key
- 支持多用户 Token 分配，便于团队协作
- 支持随时撤销 Token 而不影响真实 Key

---

## 许可证

专有软件（Proprietary）。未经授权不得商用。详见 [LICENSE](LICENSE)。

## 作者

ZeroAI Team。详见 [AUTHORS](AUTHORS)。

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。

## 贡献指南

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 致谢

- [智谱 AI](https://open.bigmodel.cn/) - GLM 系列模型
- [Textual](https://textual.textualize.io/) - TUI 框架
- [asyncssh](https://asyncssh.readthedocs.io/) - 异步 SSH 客户端
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) - 语音识别
- [Semantic Scholar](https://www.semanticscholar.org/) - 学术文献数据
- [FastAPI](https://fastapi.tiangolo.com/) - 代理服务框架

---

<div align="center">

**ZeroAI — 让科研协作更高效**

</div>
