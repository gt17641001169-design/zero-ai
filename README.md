<div align="center">

# ZeroAI

### 终端 AI 编程助手 + AI 远程运维

**多专家协作 · 语音对话 · 文档生成 · 安全审计 · SSH 远程部署 · AI 运维**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-green.svg)]()
[![License](https://img.shields.io/badge/License-Proprietary-orange.svg)]()

</div>

---

## 简介

ZeroAI 是一个功能完整的终端 AI 助手，对标 OpenCode，专为开发者和研究人员设计。集成 7 位 AI 专家协同工作，支持语音对话、文档生成、安全审计、文献检索等功能，**并具备 SSH 远程部署 + AI 远程运维能力**，可远程帮用户部署项目、诊断服务器、管理服务/Docker/防火墙等，开箱即用。

## 核心特性

### 🤖 多专家协作
- **7 位专家**：项目经理（GLM-4V 多模态）、编程（GLM-4.7）、推理、通用知识、中文写作、多模态视觉、学术研究
- **自动路由**：根据问题关键词自动分配到最合适的专家
- **混合思考**：多专家协作处理同一问题，项目经理汇总
- **手动模式**：可手动指定模型（GLM / OpenRouter / Ollama）

### 🚀 SSH 远程部署（7 个工具）
- **多服务器并行连接**：通过 `conn_id` 区分不同服务器，支持密码/密钥认证
- **远程命令执行**：危险命令（rm -rf /、mkfs、dd 等 11 类）二次确认
- **SFTP 文件传输**：上传/下载文件，自动设置权限
- **一键自动化部署**：`ssh_deploy` 7 步骤（pre_check → mkdir → upload → install → restart → health_check → post_cmds）
- **审计日志**：所有 SSH 操作自动记录（最多 200 条），可追溯
- **安全设计**：主机地址校验、危险命令黑名单、内网IP可选阻断、输出截断保护

### 🛠️ AI 远程运维（8 个语义化工具）
**核心升级**：把"AI 拼命令"升级为"AI 调用语义化工具"，减少幻觉、统一错误处理、自动分析结果。
- **服务管理** `ssh_service_manage`：systemd 封装（status/start/stop/restart/enable）
- **日志分析** `ssh_log_view`：journalctl 封装，自动统计错误密度
- **进程查看** `ssh_process_check`：按 CPU/内存排序 Top N
- **磁盘分析** `ssh_disk_analyze`：df + du Top10，自动标注危急/警告
- **网络诊断** `ssh_network_diag`：端口/连接/ping/统计
- **Docker 管理** `ssh_docker_manage`：容器/镜像/日志/资源
- **防火墙管理** `ssh_firewall_manage`：自动识别 ufw/firewalld/iptables
- **一键体检** `ssh_health_check`：综合报告 + AI 健康分析 + 异常项标注

### 🧠 AI 运维决策链（自主诊断）
- **模糊问题处理**："服务器卡了" → 先体检 → 再深入 → 定位 → 给建议
- **明确故障排错**："nginx 挂了" → 看 status → 若 failed → 查 error 日志 → 定位根因
- **AI 主动分析**：体检报告自动识别负载/磁盘/Swap/失败服务/错误日志异常项

### 🎙️ 语音对话
- **离线语音识别**：基于 SenseVoice（阿里达摩院），支持中英日韩粤 5 语言，无需 API Key
- **语音合成**：Edge TTS，支持男女声切换、语速调节
- **实时字幕**：对话模式下显示实时字幕
- **快捷操作**：Ctrl+T 单次语音输入，Ctrl+D 持续对话模式

### 📄 文档生成
- **国标格式**：按 GB/T 7713.1-2025 生成 Word/PDF 文档
- **四级标题**：支持 `#` 到 `####` 四级标题渲染
- **学术公式**：LaTeX → Unicode 渲染（分数、根号、矩阵、极限、求和、积分等）
- **PDF 公式图片**：独立公式 `$$...$$` 通过 matplotlib mathtext 渲染为高清图片
- **参考文献**：自动格式化引用

### 🔒 安全审计
- **漏洞扫描**：SQL 注入、XSS、硬编码密钥、路径遍历等
- **依赖检查**：扫描依赖包已知漏洞
- **配置审计**：检查配置文件安全问题
- **非侵入式**：仅扫描自身项目，不进行渗透测试

### 📚 文献检索
- **Semantic Scholar**：集成 2 亿+学术论文数据库
- **智能筛选**：按年份、引用数、影响力排序
- **免费无需 Key**：直接使用

### ⚡ 其他特性
- **流式输出**：实时显示 AI 思考过程和回复
- **上下文压缩**：长对话自动压缩，节省 Token
- **图片输入**：粘贴剪贴板图片或输入图片路径（多模态）
- **代码工具**：读写文件、执行命令、代码搜索

## 安装

### 方式一：pip 安装（推荐）

```bash
pip install zero-ai-cli
```

### 方式二：从源码安装

```bash
git clone <仓库地址>
cd zero-ai-cli
pip install -e .
```

### 可选：安装语音功能

```bash
pip install zero-ai-cli[voice]
```

语音功能包含：sherpa-onnx（语音识别）、faster-whisper（备用识别）、av（音频处理）。

首次使用语音功能时，会自动从 HuggingFace 镜像下载 SenseVoice 模型（约 220MB），下载后离线运行。

## 使用

安装后在任意终端输入：

```bash
zeroai
```

### 首次使用配置

首次启动需要配置 AI 模型的 API Key：

1. **获取 GLM API Key**（免费）：
   - 访问 https://open.bigmodel.cn/
   - 注册账号，在 API Keys 页面创建 Key
   - 免费额度充足，无需付费

2. **配置 Key**：
   - 启动 ZeroAI 后按 `Ctrl+P` 打开设置面板
   - 填入 GLM API Key 并保存
   - 或设置环境变量：`ZEROAI_API_KEY_GLM=你的Key`

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

### 专家团队

| 专家 | 模型 | 职责 |
|------|------|------|
| 项目经理 | GLM-4V | 任务分析、调度、多模态（支持图片） |
| 编程 | GLM-4.7 | 代码生成、调试、重构 |
| 推理 | 内置免费模型 | 深度推理、数学、逻辑 |
| 通用知识 | GLM-4.7 | 通用问答、翻译、百科 |
| 中文写作 | 内置免费模型 | 中文写作、文案、报告 |
| 多模态 | GLM-4V | 图片理解、图文分析 |
| 学术研究 | GLM-4.7 | 学术研究、公式推导、论文写作 |

## 系统要求

- **Python** >= 3.10
- **操作系统**：Windows / macOS / Linux
- **网络**：需要访问智谱 GLM API（`open.bigmodel.cn`）
- **语音功能**：需要麦克风（仅语音对话模式）
- **多模态**：支持 png/jpg/jpeg/gif/bmp/webp 格式图片

## 配置

### 配置文件位置

- **Windows**：`%USERPROFILE%\.zeroai\config.json`
- **macOS/Linux**：`~/.zeroai/config.json`

### 环境变量

| 环境变量 | 说明 |
|---------|------|
| `ZEROAI_API_KEY_GLM` | 智谱 GLM API Key |
| `ZEROAI_API_KEY_OPENROUTER` | OpenRouter API Key |
| `ZEROAI_HOME` | ZeroAI 资源目录（libs/models 所在位置） |

### 资源目录

语音模型等资源文件查找顺序：

1. 脚本所在目录（开发模式）
2. `ZEROAI_HOME` 环境变量指定的目录
3. 用户主目录 `~/.zeroai/`（pip 安装模式）

## 技术栈

| 组件 | 技术 |
|------|------|
| UI 框架 | Textual TUI |
| AI 接口 | OpenAI SDK（兼容 GLM API） |
| **SSH 远程** | **asyncssh（纯 Python 异步 SSH）** |
| 语音识别 | sherpa-onnx + SenseVoice（离线） |
| 语音合成 | Edge TTS |
| 文档生成 | python-docx + reportlab + matplotlib |
| 学术公式 | LaTeX → Unicode + matplotlib mathtext |
| 文献检索 | Semantic Scholar API |

## 功能演示

### 多专家协作

```
用户：帮我写一个 Python 函数计算斐波那契数列，并分析时间复杂度

→ 项目经理·GLM-4V 分析任务
→ 编程·GLM-4.7 生成代码
→ 推理·内置 分析复杂度
→ 项目经理·GLM-4V 汇总结果
```

### 语音对话

```
按 Ctrl+D 进入语音对话模式
→ 说话："什么是递归"
→ AI 语音回答 + 实时字幕显示
→ 继续说话或按 ESC 退出
```

### 文档生成

```
用户：请生成一份关于机器学习的学术报告，Word 格式

→ 学术研究·GLM-4.7 生成内容
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
  4. install   → pip install -r requirements.txt
  5. restart   → systemctl restart myapp
  6. health_check → curl localhost:8080/health
  7. post_cmds → 清理临时文件
→ 生成部署报告
```

### AI 远程运维（语义化工具）

```
用户：服务器卡了，看看怎么回事

→ ssh_health_check 一键体检
  → 系统信息、CPU、内存、磁盘、网络、负载、失败服务、错误日志
  → AI 分析：发现 3 个问题
    1. ⚠️ 1分钟负载 5.2 偏高
    2. ⚠️ 磁盘使用率 92%（危急）
    3. ⚠️ 最近1小时有 15 条错误日志
→ 建议深入排查

用户：mysql 状态怎么样

→ ssh_service_manage(action=status, service=mysql)
→ 自动状态解读：✅ 服务运行中 / ⚠️ 服务未运行 / ❌ 异常退出

用户：查 nginx 的 error 日志

→ ssh_log_view(service=nginx, keyword=error)
→ 返回日志 + 自动统计：错误密度高，建议深入排查

用户：开放 8080 端口

→ ssh_firewall_manage(action=open, port=8080)
→ 自动识别防火墙类型（ufw/firewalld/iptables）并执行
```

## 开发

### 开发模式安装

```bash
git clone <仓库地址>
cd zero-ai-cli
pip install -e .
```

开发模式下修改 `tui_agent.py` 即时生效，无需重新安装。

### 构建

#### 方式一：pip 包构建

```bash
pip install build
python -m build
```

生成的包在 `dist/` 目录。

#### 方式二：PyInstaller 单文件 EXE

```bash
pip install pyinstaller
pyinstaller ZeroAI.spec
```

打包后生成 `dist/ZeroAI.exe` 单文件，包含所有依赖（含 asyncssh、语音模型、文档生成库等）。

### 项目结构

```
zero-ai-cli/
├── tui_agent.py          # 主程序（单文件架构，含 48 个工具）
├── ollama_chat.py        # Ollama 集成
├── ollama_agent.py       # Ollama Agent
├── terminal_agent.py     # 终端 Agent
├── pyproject.toml        # 包配置
├── ZeroAI.spec           # PyInstaller 打包配置
├── README.md             # 说明文档
├── install.bat           # Windows 一键安装脚本
├── assets/               # 图标资源
│   └── icons/
├── libs/                 # 语音依赖库（开发模式）
└── models/               # 语音识别模型（开发模式）
```

## 常见问题

### Q: 启动后提示"请配置 GLM API Key"？

A: 按 `Ctrl+P` 打开设置面板，填入智谱 GLM API Key。免费获取：https://open.bigmodel.cn/

### Q: 语音功能无法使用？

A: 1. 确认已安装语音依赖：`pip install zero-ai-cli[voice]`
   2. 首次使用会自动下载模型（约 220MB）
   3. 确认麦克风权限已开启

### Q: 提示 RateLimitError（限流）？

A: GLM 免费额度有限，系统会自动降级到其他模型。如频繁限流，可：
   - 在智谱平台升级额度
   - 配置 OpenRouter 作为备用
   - 使用自己的 GLM API Key

### Q: 支持 macOS / Linux 吗？

A: 核心功能支持。语音功能在 macOS/Linux 上可能需要额外配置音频驱动。

### Q: SSH 远程运维怎么使用？

A: 1. 直接用自然语言告诉 AI："连接到 192.168.10.22，用户 root，密码 xxx"
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
"把 D:/项目/myapp 部署到 192.168.10.22 的 /opt/myapp，
 安装依赖 pip install -r requirements.txt，
 重启命令 systemctl restart myapp，
 健康检查 curl localhost:8080/health"
```
AI 会自动执行 7 步骤并生成部署报告。

## 许可证

专有软件（Proprietary）。未经授权不得商用。

## 作者

ZeroAI Team

## 致谢

- [智谱 AI](https://open.bigmodel.cn/) - GLM 系列模型
- [Textual](https://textual.textualize.io/) - TUI 框架
- [asyncssh](https://asyncssh.readthedocs.io/) - 异步 SSH 客户端
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) - 语音识别
- [Semantic Scholar](https://www.semanticscholar.org/) - 学术文献数据

---

<div align="center">

**如果觉得有用，请给个 Star ⭐**

</div>
