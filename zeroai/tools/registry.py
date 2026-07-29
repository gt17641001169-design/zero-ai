"""工具注册中心

迁移来源：tui_agent.py 行 8832-9331

提供：
- TOOLS：工具 schema 列表（OpenAI Function Calling 格式）
- TOOL_MAP：工具名 -> 工具函数映射

所有工具函数均来自 zeroai.tools 子模块，本模块只负责聚合 schema 和映射，
不持有任何工具实现，便于按需扩展和单元测试。

设计约束：
- TOOLS 中声明的函数名必须与 TOOL_MAP 的 key 完全一致
- TOOL_MAP 的 value 必须是可调用对象（同步或异步函数均可）
- 新增工具时，只需在对应子模块实现函数，然后在此导入并注册
"""
from zeroai.tools.file_manager import (
    read_file,
    write_file,
    list_dir,
    search_files,
    delete_file,
    move_file,
    copy_file,
    create_dir,
    edit_file,
    file_diff,
    read_image,
)
from zeroai.tools.command_exec import (
    run_command,
    exec_python,
    pip_install,
)
from zeroai.tools.network import (
    open_app,
    web_search,
    web_fetch,
    git_status,
)
from zeroai.tools.system_check import (
    system_info,
    process_list,
    check_port,
    local_port_check,
    local_process_check,
    local_disk_check,
    local_service_check,
    local_firewall_check,
    local_user_check,
    local_monitor,
)
from zeroai.tools.security import security_audit
from zeroai.tools.doc_gen import (
    generate_word,
    generate_excel,
    generate_pdf,
)
from zeroai.tools.academic import (
    academic_search,
    arxiv_search,
    citation_check,
    literature_review,
    render_formula,
)
from zeroai.tools.window_mgr import (
    active_window,
    list_windows,
    read_screen_content,
)
from zeroai.tools.ssh_ops import (
    ssh_connect,
    ssh_exec,
    ssh_upload,
    ssh_download,
    ssh_deploy,
    ssh_setup_samba_share,
    ssh_list,
    ssh_disconnect,
    ssh_service_manage,
    ssh_log_view,
    ssh_process_check,
    ssh_disk_analyze,
    ssh_network_diag,
    ssh_docker_manage,
    ssh_firewall_manage,
    ssh_health_check,
)
from zeroai.tools.voice import (
    speak_tts,
    listen_asr,
)
from zeroai.tools.command_exec import (
    code_execute,
    code_check,
)
from zeroai.tools.command_exec import (
    code_graph_index,
    code_graph_query,
    code_graph_stats,
)


# ============================================================================
# TOOLS：OpenAI Function Calling 工具 schema 列表
# 迁移来源：tui_agent.py 行 8832-9281
# ============================================================================
TOOLS = [
    {"type": "function", "function": {
        "name": "read_file", "description": "读取本地文件内容",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "max_length": {"type": "integer", "description": "最大返回字符数，默认3000"}},
            "required": ["path"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "写入或创建文件",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "文件内容"}},
            "required": ["path", "content"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "list_dir", "description": "列出目录内容，支持递归显示子目录树形结构。当用户问有哪些文件、目录结构、查看文件夹、深入子文件夹时调用。recursive=true时会自动深入到最深层目录（默认15层，自动跳过无权限目录）。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "目录路径，默认当前目录"},
            "recursive": {"type": "boolean", "description": "是否递归显示子目录（树形结构），默认false只显示一层，true自动深入到最深层目录"},
            "max_depth": {"type": "integer", "description": "递归最大深度（默认15=深入最深层，1=只看当前层）"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "run_command", "description": "在本地电脑执行 PowerShell / cmd / shell 命令并返回输出。全权限模式：120s 超时、8000 字符输出。用于查看端口(netstat)、进程(tasklist)、网络(ipconfig/ping/tracert)、系统信息(systeminfo)、服务(sc query/net start)、用户(whoami/net user)、磁盘(wmic logicaldisk)、防火墙(netsh advfirewall)、环境变量(set)等。当用户用自然语言描述本地电脑状态需求（如'看看打开了哪些端口'/'电脑卡不卡'/'谁在占用CPU'/'IP是多少'）且没有更专用的工具时调用。危险命令(format/del /f/shutdown/mkfs)自动拦截。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的命令（PowerShell 或 cmd 命令）"}},
            "required": ["command"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "search_files", "description": "在文件内容中搜索正则",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "正则"},
            "path": {"type": "string", "description": "目录"}},
            "required": ["pattern"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "open_app", "description": "打开桌面应用程序。支持：微信、QQ、VSCode、PyCharm、Edge、记事本、计算器、资源管理器、画图、任务管理器、控制面板、注册表、CMD、PowerShell 等。当用户让你打开/启动某个应用时调用。",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "应用名称（中英文均可），如：微信、wechat、qq、vscode、pycharm、edge、记事本、计算器"}},
            "required": ["name"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "web_search", "description": "网络搜索，获取搜索结果。当用户问实时信息、新闻、文档、最新动态时调用。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "num_results": {"type": "integer", "description": "返回结果数量，默认5"}},
            "required": ["query"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "web_fetch", "description": "抓取网页内容，获取网页纯文本。当需要读取某个 URL 的内容时调用。",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "网页 URL"},
            "max_length": {"type": "integer", "description": "最大返回字符数，默认4000"}},
            "required": ["url"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "git_status", "description": "查看 Git 仓库状态（分支、改动文件）。当用户问 git 状态、代码变更时调用。",
        "parameters": {"type": "object", "properties": {
            "repo_path": {"type": "string", "description": "仓库路径，默认当前目录"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "delete_file", "description": "删除文件或目录（优先移入回收站）。当用户让你删除文件时调用。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "要删除的文件或目录路径"}},
            "required": ["path"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "move_file", "description": "移动或重命名文件。当用户让你移动、重命名文件时调用。",
        "parameters": {"type": "object", "properties": {
            "src": {"type": "string", "description": "源文件路径"},
            "dst": {"type": "string", "description": "目标路径"}},
            "required": ["src", "dst"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "copy_file", "description": "复制文件。当用户让你复制、备份文件时调用。",
        "parameters": {"type": "object", "properties": {
            "src": {"type": "string", "description": "源文件路径"},
            "dst": {"type": "string", "description": "目标路径"}},
            "required": ["src", "dst"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "create_dir", "description": "创建目录（含父目录）。当用户让你创建文件夹时调用。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "目录路径"}},
            "required": ["path"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "system_info", "description": "获取系统信息（CPU、内存、磁盘）。当用户问系统状态、环境信息时调用。",
        "parameters": {"type": "object", "properties": {},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "process_list", "description": "列出进程。当用户问运行中的进程、查看进程时调用。",
        "parameters": {"type": "object", "properties": {
            "name_filter": {"type": "string", "description": "进程名过滤关键词"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "edit_file", "description": "按行编辑文件：替换/插入/删除/追加指定行。当需要修改文件中的某一行或某几行时调用，避免重写整个文件。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "operation": {"type": "string", "description": "操作类型：replace（替换行）/ insert（插入行）/ delete（删除行）/ append（末尾追加）"},
            "line": {"type": "integer", "description": "目标行号（从1开始），replace/insert用"},
            "content": {"type": "string", "description": "新内容（replace/insert/append用）"},
            "start_line": {"type": "integer", "description": "删除起始行号（delete用）"},
            "end_line": {"type": "integer", "description": "删除结束行号（delete用）"}},
            "required": ["path", "operation"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "exec_python", "description": "在安全沙箱中执行 Python 代码片段并返回结果。用于快速验证算法、计算表达式、数据处理。当用户让你运行Python代码、计算、验证时调用。",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Python 代码片段"}},
            "required": ["code"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "pip_install", "description": "Python 包管理。当用户让你安装/卸载/查看Python包时调用。",
        "parameters": {"type": "object", "properties": {
            "package": {"type": "string", "description": "包名（list操作时留空）"},
            "action": {"type": "string", "description": "操作：install（安装）/ uninstall（卸载）/ check（检查）/ list（列出已安装）"}},
            "required": ["action"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "code_execute", "description": "在安全沙箱中执行 Python 代码（阶段 N.2）。使用 AST 静态分析 + 子进程隔离的双重保护，禁止危险调用（os.system/subprocess 等），默认禁用网络访问。当用户让你运行复杂Python代码、数据分析、算法验证时调用，比 exec_python 更安全。",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Python 代码"},
            "timeout": {"type": "integer", "description": "超时秒数（1-60，默认10）"},
            "stdin_input": {"type": "string", "description": "标准输入内容（可选）"}},
            "required": ["code"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "code_check", "description": "检查 Python 代码安全性（阶段 N.2，不执行）。静态分析代码中的危险调用，返回检查结果。当用户想验证代码是否安全时调用。",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Python 代码"}},
            "required": ["code"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "code_graph_index", "description": "构建项目代码知识图谱（阶段 Q.1）。扫描指定目录下的 Python 文件，使用 AST 解析提取模块/类/函数节点及调用/继承/导入关系。当用户问代码结构、调用关系、继承关系、想分析项目架构时调用。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "项目目录路径，默认当前目录"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "code_graph_query", "description": "自然语言查询代码结构（阶段 Q.2）。基于已构建的代码知识图谱，回答关于代码结构的自然语言问题。支持：谁调用了X/X的子类/X定义在哪里/X的调用链等。需先调用 code_graph_index 构建索引。",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "自然语言问题，如'谁调用了 run_command 函数？'、'AgentLoop 的子类有哪些？'、'run 函数定义在哪里？'"}},
            "required": ["question"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "code_graph_stats", "description": "获取代码知识图谱统计信息（阶段 Q.2）。返回节点数、边数、模块数等统计。当用户问代码规模、图谱状态时调用。",
        "parameters": {"type": "object", "properties": {},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "check_port", "description": "检测端口占用情况，返回占用进程信息。当用户问端口占用、服务是否启动时调用。",
        "parameters": {"type": "object", "properties": {
            "port": {"type": "integer", "description": "端口号"}},
            "required": ["port"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "file_diff", "description": "比较两个文件的差异，返回逐行diff。当用户问文件区别、对比文件时调用。",
        "parameters": {"type": "object", "properties": {
            "path_a": {"type": "string", "description": "第一个文件路径"},
            "path_b": {"type": "string", "description": "第二个文件路径"}},
            "required": ["path_a", "path_b"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "read_image", "description": "读取图片文件并理解内容。支持 png/jpg/jpeg/gif/bmp/webp 格式。当用户发送图片路径或让你看图片时调用。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "图片文件路径"}},
            "required": ["path"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "active_window", "description": "获取当前焦点窗口信息（标题、应用名、位置大小）。当用户问当前在做什么、当前窗口时调用。",
        "parameters": {"type": "object", "properties": {},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "list_windows", "description": "列出所有可见窗口及其标题和PID。当用户问打开了哪些窗口、桌面上的程序时调用。",
        "parameters": {"type": "object", "properties": {},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "read_screen", "description": "读取当前前台窗口的文字内容（通过UI Automation，像屏幕阅读器一样精确读取文字）。当用户问屏幕上有什么、当前页面内容、看到什么时调用。",
        "parameters": {"type": "object", "properties": {},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "security_audit", "description": "安全审计：扫描代码漏洞、敏感信息、依赖漏洞、配置安全。当用户让你检查安全、查找漏洞、安全审计、扫描代码问题时调用。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "要扫描的文件或目录路径，默认为当前目录"},
            "scan_type": {"type": "string", "description": "扫描类型：all(全部) / code(代码漏洞) / secret(敏感信息) / deps(依赖漏洞) / config(配置安全)"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "generate_word", "description": "生成 Word 文档（.docx），支持指定格式模板和高级排版。当用户让你生成Word文档、写报告、合同、简历、论文、学术文章、导出文档时调用。支持8种模板（含academic学术论文模板：双倍行距/摘要/关键词/参考文献自动编号/LaTeX公式渲染）、自定义字体/颜色/页边距/对齐/页眉页脚/表格。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "保存路径（可选，默认保存到桌面）。可传完整路径如 D:/报告.docx，或只传文件名如 报告.docx（自动保存到桌面），或留空（自动命名保存到桌面）"},
            "content": {"type": "string", "description": "文档内容（支持 Markdown 标记：# 标题 / - 列表 / > 引用 / ```代码``` / **粗体** *斜体* `代码` ~~删除线~~ / |表格| / [居中]行首对齐 / {color:红色}文字{/color}）"},
            "title": {"type": "string", "description": "文档标题（可选，留空则取内容第一行 # 标题）"},
            "template": {"type": "string", "description": "格式模板：default(默认) / report(正式报告) / contract(合同) / resume(简历) / thesis(论文) / letter(信函) / technical(技术文档) / academic(学术论文：双倍行距+摘要+关键词+参考文献自动编号+LaTeX公式渲染)"},
            "font": {"type": "string", "description": "覆盖模板字体，如 SimSun(宋体) / Microsoft YaHei(微软雅黑) / KaiTi(楷体) / Times New Roman"},
            "font_size": {"type": "integer", "description": "覆盖模板字号，如 10/11/12/14"},
            "margin": {"type": "array", "items": {"type": "number"}, "description": "页边距[上,右,下,左]厘米，如 [2.54, 2.54, 2.54, 2.54]"},
            "heading_color": {"type": "string", "description": "标题颜色，十六进制如 1F4E79 或颜色名如 navy/red/blue"},
            "align": {"type": "string", "description": "全文对齐：left / center / right / justify"},
            "header": {"type": "string", "description": "页眉文字"},
            "footer": {"type": "string", "description": "页脚文字，支持 {page} 和 {numpages} 占位符"}},
            "required": ["content"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "generate_excel", "description": "生成 Excel 文档（.xlsx），支持多工作表、表头样式、隔行变色、自动列宽、图表（柱状图/折线图/饼图）、公式。当用户让你生成Excel表格、数据表、导出Excel、带图表的Excel时调用。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "保存路径（可选，默认保存到桌面）。可传完整路径如 D:/数据表.xlsx，或只传文件名如 数据表.xlsx（自动保存到桌面），或留空（自动命名保存到桌面）"},
            "sheets": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string", "description": "工作表名（可选，默认Sheet1）"},
                "data": {"type": "array", "items": {"type": "array"}, "description": "数据二维数组，第一行作为表头"},
                "header": {"type": "boolean", "description": "是否有表头，默认true"}
            }, "required": ["data"]}, "description": "工作表列表"},
            "template": {"type": "string", "description": "格式模板：default(默认蓝) / report(报告深蓝) / data(数据绿) / financial(财务灰)"},
            "charts": {"type": "array", "items": {"type": "object", "properties": {
                "type": {"type": "string", "description": "图表类型：bar(柱状图) / line(折线图) / pie(饼图)"},
                "title": {"type": "string", "description": "图表标题"},
                "sheet": {"type": "string", "description": "数据所在工作表名"},
                "categories_col": {"type": "string", "description": "分类轴列号，如 A（姓名列）"},
                "values_cols": {"type": "array", "items": {"type": "string"}, "description": "值轴列号列表，如 [\"B\",\"C\"]"},
                "position": {"type": "string", "description": "图表放置位置单元格，如 E2"}
            }, "required": ["type", "sheet", "categories_col", "values_cols"]}, "description": "图表列表（可选）"},
            "formulas": {"type": "array", "items": {"type": "object", "properties": {
                "sheet": {"type": "string", "description": "工作表名"},
                "cell": {"type": "string", "description": "写入单元格，如 D2"},
                "formula": {"type": "string", "description": "公式，如 =AVERAGE(C2:C4) 或 =SUM(B2:B5)"}
            }, "required": ["sheet", "cell", "formula"]}, "description": "公式列表（可选）"}},
            "required": ["sheets"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "generate_pdf", "description": "生成 PDF 文档，支持Markdown标记和多种模板。当用户让你生成PDF、导出PDF、写报告PDF、学术论文PDF时调用。支持7种模板（含academic学术论文模板）。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "保存路径（可选，默认保存到桌面）。可传完整路径如 D:/报告.pdf，或只传文件名如 报告.pdf（自动保存到桌面），或留空（自动命名保存到桌面）"},
            "content": {"type": "string", "description": "文档内容（支持 Markdown 标记：# 标题 / - 列表 / > 引用 / ```代码``` / **粗体** *斜体* / |表格| / --- 分隔线 / $LaTeX公式$）"},
            "title": {"type": "string", "description": "文档标题（可选）"},
            "template": {"type": "string", "description": "格式模板：default(默认) / report(报告) / contract(合同) / resume(简历) / letter(信函) / technical(技术文档) / academic(学术论文：1.5倍行距+摘要+关键词+参考文献自动编号+LaTeX公式渲染)"}},
            "required": ["content"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "render_formula", "description": "渲染 LaTeX 数学公式为终端可显示的 Unicode 文本。当用户写数学公式、物理方程、化学方程式、统计公式、需要学术符号展示时调用。支持希腊字母、上下标、分数、根号、求和、积分、矩阵符号等。",
        "parameters": {"type": "object", "properties": {
            "latex": {"type": "string", "description": r"LaTeX 公式字符串，如 'E=mc^2' 或 '\\sum_{i=1}^{n} x_i^2' 或 '\\frac{\\partial f}{\\partial x}'"},
            "style": {"type": "string", "description": "渲染样式：unicode(默认，终端显示) / raw(原始LaTeX) / latex($$包裹)"}},
            "required": ["latex"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "academic_search", "description": "学术文献搜索（Semantic Scholar，2亿+论文）。当用户查找论文、文献、学术研究、引用、DOI时调用。支持按年份、引用数、影响力筛选。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词（中英文均可），如 'attention is all you need' 或 '深度学习综述'"},
            "num_results": {"type": "integer", "description": "返回结果数量，默认5，最大20"},
            "year_from": {"type": "integer", "description": "起始年份（如 2020），0或省略表示不限"},
            "year_to": {"type": "integer", "description": "结束年份（如 2024），0或省略表示不限"},
            "sort_by": {"type": "string", "description": "排序方式：relevance(相关性，默认) / citations(引用数) / influence(影响力)"}},
            "required": ["query"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "arxiv_search", "description": "arXiv 预印本论文搜索（物理/数学/计算机/统计）。查找最新研究、未正式发表的论文时调用。英文关键词效果更佳。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词（英文效果更佳），如 'transformer attention' 或 'graph neural network'"},
            "num_results": {"type": "integer", "description": "返回结果数量，默认5，最大20"},
            "sort_by": {"type": "string", "description": "排序方式：relevance(相关性，默认) / submittedDate(最新提交) / lastUpdatedDate(最近更新)"},
            "category": {"type": "string", "description": "学科分类筛选，如 cs.AI(人工智能) / cs.CL(计算语言学) / cs.LG(机器学习) / math.AG(代数几何) / physics(物理) / stat.ML(统计机器学习)。留空表示不限"}},
            "required": ["query"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "citation_check", "description": "文献引用真实性校验（防止AI编造不存在的文献）。引用任何文献前必须调用此工具验证。支持标题匹配、DOI查询、arXiv ID查询三种方式。",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "文献标题（精确或近似标题），如 'Attention Is All You Need'"},
            "doi": {"type": "string", "description": "文献的 DOI，如 '10.1038/s41586-021-03819-2'"},
            "arxiv_id": {"type": "string", "description": "arXiv 编号，如 '2301.00234'"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "literature_review", "description": "文献综述自动分析。双源检索(Semantic Scholar+arXiv)+去重+结构化对比分析表+趋势统计+PRISMA筛选流程+研究空白识别。用户写综述/文献分析时调用。",
        "parameters": {"type": "object", "properties": {
            "topic": {"type": "string", "description": "研究主题（中英文均可），如 '钠离子电池层状氧化物正极' 或 'sodium-ion battery layered oxide cathode'"},
            "num_papers": {"type": "integer", "description": "分析文献数量，默认10，最大20"},
            "year_from": {"type": "integer", "description": "起始年份（如 2018），0表示不限"},
            "year_to": {"type": "integer", "description": "结束年份（如 2025），0表示不限"}},
            "required": ["topic"],
            "additionalProperties": False}}},
    # ====== SSH 远程部署工具 ======
    {"type": "function", "function": {
        "name": "ssh_connect", "description": "连接到远程SSH服务器（Linux/Windows 均可）。支持密码和密钥认证。连接成功后保持长连接，支持多服务器并行（通过 conn_id 区分）。当用户要求远程部署、SSH连接、服务器管理时调用。多服务器场景务必传 remark 标注用途防混淆。",
        "parameters": {"type": "object", "properties": {
            "host": {"type": "string", "description": "服务器地址（IP或域名，如 192.168.1.100）"},
            "user": {"type": "string", "description": "登录用户名（如 root / deploy / ubuntu / administrator）"},
            "password": {"type": "string", "description": "密码认证（与key_path二选一）"},
            "key_path": {"type": "string", "description": "SSH私钥路径（如 ~/.ssh/id_rsa），与password二选一"},
            "port": {"type": "integer", "description": "SSH端口，默认22"},
            "conn_id": {"type": "string", "description": "连接标识符，多服务器时区分，默认'default'。建议起有意义的名字如 'nas'/'web1'/'db1'"},
            "remark": {"type": "string", "description": "服务器备注/角色（如 'NAS存储'/'Web前端'/'数据库'），多服务器场景防混淆必填"}},
            "required": ["host", "user"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_exec", "description": "在远程服务器执行Shell命令（Linux/Windows 自动适配，Windows 下走 cmd/PowerShell）。需要先ssh_connect。危险命令需confirm_dangerous=true。当用户要求远程执行命令、查看状态、部署时调用。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "Shell命令（如 'ls -la /opt'、'systemctl status nginx'）"},
            "conn_id": {"type": "string", "description": "连接ID，默认'default'"},
            "timeout": {"type": "integer", "description": "超时秒数，默认30"},
            "confirm_dangerous": {"type": "boolean", "description": "确认执行危险命令（rm -rf /等），默认false"}},
            "required": ["command"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_upload", "description": "上传本地文件到远程服务器（SFTP）。需要先ssh_connect。当用户要求推送文件、上传代码、传输配置时调用。",
        "parameters": {"type": "object", "properties": {
            "local_path": {"type": "string", "description": "本地文件路径"},
            "remote_path": {"type": "string", "description": "远程目标完整路径（如 /opt/myapp/config.yml）"},
            "conn_id": {"type": "string", "description": "连接ID，默认'default'"}},
            "required": ["local_path", "remote_path"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_download", "description": "从远程服务器下载文件到本地（SFTP）。需要先ssh_connect。当用户要求拉取日志、备份文件、下载配置时调用。",
        "parameters": {"type": "object", "properties": {
            "remote_path": {"type": "string", "description": "远程文件路径"},
            "local_path": {"type": "string", "description": "本地保存路径"},
            "conn_id": {"type": "string", "description": "连接ID，默认'default'"}},
            "required": ["remote_path", "local_path"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_deploy", "description": "一键项目部署（自动化多步骤部署）。按顺序：环境检查→创建目录→上传代码→安装依赖→重启服务→健康检查。当用户要求部署项目、自动化发布时调用。",
        "parameters": {"type": "object", "properties": {
            "deploy_config": {"type": "object", "description": "部署配置，包含: pre_check(检查命令列表), remote_dir(部署目录), upload_files([[local,remote],...]), install_cmd(安装命令), restart_cmd(重启命令), health_check(健康检查命令), post_cmds(后置命令列表)"},
            "conn_id": {"type": "string", "description": "连接ID，默认'default'"}},
            "required": ["deploy_config"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_setup_samba_share", "description": "一键配置 Samba 共享文件夹（Linux 服务器专用，8 步骤自动完成：安装+配置+启动+防火墙+SELinux+验证）。当用户说'共享文件夹/配置Samba/让Windows能访问Linux文件/文件共享/SMB共享'时调用。Windows Server 共享请用 ssh_exec 执行 New-SmbShare。",
        "parameters": {"type": "object", "properties": {
            "share_name": {"type": "string", "description": r"共享名（Windows 访问时用，如 'shared'，访问路径 \\IP\shared），默认 'shared'"},
            "share_path": {"type": "string", "description": "共享文件夹在 Linux 上的路径，默认 '/srv/shared'"},
            "access_mode": {"type": "string", "enum": ["guest_ro", "guest_rw", "user_rw"], "description": "权限模式：guest_ro=匿名只读 / guest_rw=匿名读写（内网推荐，默认）/ user_rw=用户认证读写（需密码，更安全）"},
            "samba_password": {"type": "string", "description": "Samba 密码（仅 user_rw 模式必填，其他模式留空）"},
            "conn_id": {"type": "string", "description": "SSH连接ID，默认'default'"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_list", "description": "查看SSH连接状态和操作审计日志。当用户问连接状态、SSH审计、操作记录时调用。留空查看所有连接。",
        "parameters": {"type": "object", "properties": {
            "conn_id": {"type": "string", "description": "指定连接ID查看详情，留空查看全部"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_disconnect", "description": "断开SSH连接。当用户要求断开、关闭连接、部署完成后清理时调用。",
        "parameters": {"type": "object", "properties": {
            "conn_id": {"type": "string", "description": "要断开的连接ID，默认'default'"}},
            "required": [],
            "additionalProperties": False}}},
    # ====== 本地运维工具集（4个，跨平台）======
    {"type": "function", "function": {
        "name": "local_port_check", "description": "本地端口/网络检查（跨平台）。用户说'看看打开了哪些端口/端口被占用了吗/能ping通吗/谁在占用80端口'时调用。action：list=列出所有监听端口，check=检查指定端口是否被占用，ping=ping目标主机，connections=查看活跃TCP连接。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "check", "ping", "connections"], "description": "操作类型，默认list"},
            "port": {"type": "integer", "description": "端口号（action=check 时必填）"},
            "protocol": {"type": "string", "enum": ["tcp", "udp"], "description": "协议，默认tcp"},
            "target": {"type": "string", "description": "目标主机/IP（action=ping 时必填）"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "local_process_check", "description": "本地进程查看（跨平台）。用户说'电脑卡不卡/谁在占用CPU/查chrome进程/结束PID 1234'时调用。action：top=按CPU排序前N，memory=按内存排序前N，find=按名称查找，kill=结束进程。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["top", "memory", "find", "kill"], "description": "操作类型，默认top"},
            "name": {"type": "string", "description": "进程名（action=find/kill 时使用）"},
            "pid": {"type": "integer", "description": "进程ID（action=kill 时使用，优先于name）"},
            "top_n": {"type": "integer", "description": "返回前N个进程，默认10"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "local_disk_check", "description": "本地磁盘空间分析（跨平台）。用户说'磁盘还剩多少/哪个目录占空间最大/C盘满了'时调用。action：list=列出所有磁盘及使用率，top=显示指定目录下Top10大目录。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "top"], "description": "操作类型，默认list"},
            "path": {"type": "string", "description": "action=top 时指定分析目录，默认根目录（Windows: C:\\，Linux: /）"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "local_service_check", "description": "本地服务管理（跨平台）。用户说'查看运行的服务/MySQL状态/启动docker/重启nginx'时调用。action：list=列出所有运行中的服务，status/start/stop/restart=管理指定服务。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "status", "start", "stop", "restart"], "description": "操作类型，默认list"},
            "service": {"type": "string", "description": "服务名（action=status/start/stop/restart 时必填）"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "local_firewall_check", "description": "本地防火墙检查/管理（跨平台）。用户说'看防火墙/防火墙状态/80端口放行了吗/开放8080端口/关闭80端口'时调用。action：list=列出所有规则，status=防火墙整体状态，check=检查端口是否放行，open/close=放行/关闭端口。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "status", "check", "open", "close"], "description": "操作类型，默认list"},
            "port": {"type": "integer", "description": "端口号（action=check/open/close 时必填）"},
            "protocol": {"type": "string", "enum": ["tcp", "udp"], "description": "协议，默认tcp"},
            "direction": {"type": "string", "enum": ["in", "out"], "description": "方向（in入站/out出站），默认in"},
            "rule_name": {"type": "string", "description": "规则名（action=open/close 时可选，默认自动生成）"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "local_user_check", "description": "本地用户/登录管理（跨平台）。用户说'查看用户/当前登录用户/用户列表/admin用户信息/用户所属组/登录会话'时调用。action：list=列出所有用户，current=当前登录用户，info=用户详情，groups=用户所属组，sessions=登录会话。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "current", "info", "groups", "sessions"], "description": "操作类型，默认list"},
            "username": {"type": "string", "description": "用户名（action=info/groups 时必填）"},
            "detail": {"type": "boolean", "description": "是否显示详细信息（action=list 时有效）"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "local_monitor", "description": "本地综合监控告警（跨平台）。用户说'体检/监控/检查电脑健康/系统监控/告警检查/有什么异常'时调用。一次性检查 CPU/内存/磁盘/端口/防火墙，返回结构化告警报告（危急/警告/正常/建议）。配合 schedule 工具可实现定时监控。",
        "parameters": {"type": "object", "properties": {
            "threshold_cpu": {"type": "integer", "description": "CPU 使用率告警阈值（默认 80）"},
            "threshold_disk": {"type": "integer", "description": "磁盘使用率告警阈值（默认 90）"},
            "threshold_memory": {"type": "integer", "description": "内存使用率告警阈值（默认 85）"},
            "check_ports": {"type": "string", "description": "需检查的关键端口（逗号分隔，如 '22,80,443,3306'），为空则不针对性检查"}},
            "required": [],
            "additionalProperties": False}}},
    # ====== AI 远程运维工具集（8个）======
    {"type": "function", "function": {
        "name": "ssh_service_manage", "description": "服务管理（Linux 用 systemctl，Windows 用 sc/Get-Service，自动适配操作系统）。用户说'查看服务状态/重启mysql/启动docker/设置开机自启/看看服务器运行了什么'时调用。返回结果含状态解读。支持 service='all' + action='status' 列出所有运行中的服务。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["status", "start", "stop", "restart", "reload", "enable", "disable", "is-active", "is-enabled"], "description": "操作类型"},
            "service": {"type": "string", "description": "服务名，如 nginx、mysql、docker、ssh、redis"},
            "conn_id": {"type": "string", "description": "SSH连接ID，默认'default'"}},
            "required": ["action", "service"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_log_view", "description": "查看远程日志（Linux: journalctl/syslog；Windows: Get-WinEvent 事件日志，自动适配）。用户说'看nginx日志/查错误/查mysql日志/搜error关键词'时调用。返回结果含自动异常统计。",
        "parameters": {"type": "object", "properties": {
            "service": {"type": "string", "description": "服务名——Linux: journalctl -u 服务名；Windows: 映射为日志名（app→Application, sec→Security, 空→System, 或自定义如 Microsoft-Windows-PowerShell/Operational）"},
            "lines": {"type": "integer", "description": "查看最后N行，默认100，范围10-1000"},
            "follow": {"type": "boolean", "description": "是否持续跟踪日志（会阻塞15秒，建议短时使用）"},
            "keyword": {"type": "string", "description": "关键词过滤（grep -i），如 error、exception、failed"},
            "conn_id": {"type": "string", "description": "SSH连接ID，默认'default'"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_process_check", "description": "查看远程服务器进程（按 CPU/内存排序，Linux: ps；Windows: Get-Process，自动适配）。用户说'看进程/CPU占用/内存占用/谁在占用资源'时调用。",
        "parameters": {"type": "object", "properties": {
            "sort_by": {"type": "string", "enum": ["cpu", "mem"], "description": "排序方式，默认cpu"},
            "top_n": {"type": "integer", "description": "返回前N个进程，默认15，范围5-50"},
            "conn_id": {"type": "string", "description": "SSH连接ID，默认'default'"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_disk_analyze", "description": "磁盘空间分析（Linux: df+du Top10；Windows: Get-CimInstance+Get-ChildItem Top10，自动适配）。用户说'看磁盘/磁盘满了/谁占了磁盘'时调用。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "分析的目录——Linux: 默认'/'；Windows: 默认所有盘符，或指定'C:'/'C:\\Users'等"},
            "conn_id": {"type": "string", "description": "SSH连接ID，默认'default'"}},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_network_diag", "description": "网络诊断工具集（Linux: ss/netstat；Windows: Get-NetTCPConnection，自动适配）。用户说'看端口/查看网络/能不能ping通/查看监听端口'时调用。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["stats", "ports", "ping", "connections"], "description": "诊断类型：stats=网络统计/ports=监听端口/ping=ping目标/connections=活跃连接"},
            "target": {"type": "string", "description": "ping操作的目标主机（IP/域名），仅action=ping时必填"},
            "conn_id": {"type": "string", "description": "SSH连接ID，默认'default'"}},
            "required": ["action"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_docker_manage", "description": "Docker 容器管理（跨平台：Linux 原生 Docker / Windows Docker Desktop，自动适配）。用户说'看容器/重启容器/docker日志/容器列表'时调用。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["ps", "psa", "logs", "start", "stop", "restart", "stats", "images", "info"], "description": "操作类型：ps=运行中容器/psa=所有容器/logs=查看日志/start/stop/restart=容器生命周期/stats=资源占用/images=镜像列表/info=Docker系统信息"},
            "container": {"type": "string", "description": "容器名/ID（logs/start/stop/restart必填）"},
            "conn_id": {"type": "string", "description": "SSH连接ID，默认'default'"}},
            "required": ["action"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_firewall_manage", "description": "防火墙统一管理（Linux: 自动识别 ufw/firewalld/iptables；Windows: netsh advfirewall，自动适配）。用户说'开端口/关端口/看防火墙/放行80端口'时调用。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["status", "list", "open", "close", "enable", "disable"], "description": "操作类型：status=状态/list=规则列表/open=开放端口/close=关闭端口/enable/disable=启用禁用"},
            "port": {"type": "integer", "description": "端口号（open/close时必填，范围1-65535）"},
            "protocol": {"type": "string", "enum": ["tcp", "udp"], "description": "协议，默认tcp"},
            "conn_id": {"type": "string", "description": "SSH连接ID，默认'default'"}},
            "required": ["action"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ssh_health_check", "description": "服务器一键健康体检（自动检测操作系统，支持 Linux 和 Windows Server）。用户说'体检/检查服务器/服务器怎么样/有没有问题/看看服务器运行了什么'时调用。返回综合报告（系统/CPU/内存/磁盘/网络/负载/失败服务/错误日志）+ AI健康分析。",
        "parameters": {"type": "object", "properties": {
            "conn_id": {"type": "string", "description": "SSH连接ID，默认'default'"}},
            "required": [],
            "additionalProperties": False}}},
    # ====== 语音交互工具 ======
    {"type": "function", "function": {
        "name": "speak_tts", "description": "文本转语音并播放（edge-tts，微软免费TTS，无需API Key）。长文本自动分段朗读。当用户让你朗读、说话、读出来、语音播报时调用。支持中英文混合。",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要朗读的文本（支持中英文混合，自动清理 Markdown 标记）"},
            "voice": {"type": "string", "description": "音色：zh-CN-XiaoxiaoNeural(女,默认) / zh-CN-YunxiNeural(男) / zh-CN-YunyangNeural(新闻) / zh-CN-XiaoyiNeural(温柔女)"},
            "rate": {"type": "string", "description": "语速：+0%(正常) / +10%(加速) / -10%(减速)"},
            "volume": {"type": "string", "description": "音量：+0%(正常) / +10%(更大) / -10%(更小)"}},
            "required": ["text"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "listen_asr", "description": "录音并识别为文字（本地离线，sherpa-onnx+SenseVoice，无需API Key，准确率高，支持中英日韩粤）。当用户让你听、录音、语音输入、语音识别时调用。首次使用会自动下载约220MB模型。",
        "parameters": {"type": "object", "properties": {
            "max_seconds": {"type": "integer", "description": "最长录音秒数，默认10，范围1-60"},
            "silence_seconds": {"type": "number", "description": "静音停止秒数（连续静音超过此值则停止录音），默认1.0"}},
            "required": [],
            "additionalProperties": False}}},
]


# ============================================================================
# TOOL_MAP：工具名 -> 工具函数映射
# 迁移来源：tui_agent.py 行 9283-9331
# ============================================================================
TOOL_MAP = {
    "read_file": read_file, "write_file": write_file,
    "list_dir": list_dir, "run_command": run_command,
    "search_files": search_files, "open_app": open_app,
    "web_search": web_search, "web_fetch": web_fetch,
    "git_status": git_status, "delete_file": delete_file,
    "move_file": move_file, "copy_file": copy_file,
    "create_dir": create_dir, "system_info": system_info,
    "process_list": process_list,
    "edit_file": edit_file, "exec_python": exec_python,
    "pip_install": pip_install, "code_execute": code_execute, "code_check": code_check,
    "code_graph_index": code_graph_index, "code_graph_query": code_graph_query, "code_graph_stats": code_graph_stats,
    "check_port": check_port,
    "file_diff": file_diff, "read_image": read_image,
    "active_window": active_window, "list_windows": list_windows,
    "read_screen": read_screen_content,
    "security_audit": security_audit,
    "generate_word": generate_word,
    "generate_excel": generate_excel,
    "generate_pdf": generate_pdf,
    "render_formula": render_formula,
    "academic_search": academic_search,
    "arxiv_search": arxiv_search,
    "citation_check": citation_check,
    "literature_review": literature_review,
    # SSH 远程部署工具
    "ssh_connect": ssh_connect,
    "ssh_exec": ssh_exec,
    "ssh_upload": ssh_upload,
    "ssh_download": ssh_download,
    "ssh_deploy": ssh_deploy,
    "ssh_setup_samba_share": ssh_setup_samba_share,
    "ssh_list": ssh_list,
    "ssh_disconnect": ssh_disconnect,
    # AI 远程运维工具集（高层封装，让 AI 调用语义化工具而非拼命令）
    "ssh_service_manage": ssh_service_manage,
    "ssh_log_view": ssh_log_view,
    "ssh_process_check": ssh_process_check,
    "ssh_disk_analyze": ssh_disk_analyze,
    "ssh_network_diag": ssh_network_diag,
    "ssh_docker_manage": ssh_docker_manage,
    "ssh_firewall_manage": ssh_firewall_manage,
    "ssh_health_check": ssh_health_check,
    # 本地运维工具集（跨平台）
    "local_port_check": local_port_check,
    "local_process_check": local_process_check,
    "local_disk_check": local_disk_check,
    "local_service_check": local_service_check,
    "local_firewall_check": local_firewall_check,
    "local_user_check": local_user_check,
    "local_monitor": local_monitor,
    # 语音交互工具
    "speak_tts": speak_tts,
    "listen_asr": listen_asr,
}


__all__ = ["TOOLS", "TOOL_MAP"]
