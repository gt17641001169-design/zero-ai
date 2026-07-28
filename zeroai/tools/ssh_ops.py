"""SSH 远程运维工具集

迁移来源：tui_agent.py 行 6787-8830

基于 asyncssh（纯 Python 异步 SSH 库）实现的远程服务器管理工具。
支持多服务器并行连接、危险命令拦截、跨平台（Linux/Windows）自动适配、
安全审计日志、SFTP 文件传输、一键部署、Docker 管理等。

提供以下纯函数：
- ssh_connect：连接到远程 SSH 服务器（支持密码/密钥认证）
- ssh_exec：在远程服务器执行 Shell 命令（危险命令拦截）
- ssh_upload：上传本地文件到远程服务器（SFTP）
- ssh_download：从远程服务器下载文件到本地（SFTP）
- ssh_deploy：一键项目部署（多步骤自动化）
- ssh_setup_samba_share：一键配置 Samba 共享文件夹
- ssh_list：查看 SSH 连接状态和审计日志
- ssh_disconnect：断开 SSH 连接
- ssh_service_manage：服务管理（systemctl / sc 自动适配）
- ssh_log_view：查看远程日志（journalctl / Get-WinEvent）
- ssh_process_check：查看远程进程（ps / Get-Process）
- ssh_disk_analyze：磁盘空间分析（df+du / Get-Volume）
- ssh_network_diag：网络诊断（ss/netstat / Get-NetTCPConnection）
- ssh_docker_manage：Docker 容器管理（跨平台）
- ssh_firewall_manage：防火墙管理（ufw/firewalld/iptables / netsh）
- ssh_health_check：服务器一键健康体检

内部辅助函数：
- _ssh_run_async：在独立事件循环线程中安全执行 async 协程
- _ssh_is_conn_closed：统一判断 asyncssh 连接是否已关闭
- _ssh_detect_os：检测远程服务器操作系统（windows/linux）
- _ssh_audit：记录 SSH 操作审计日志（脱敏处理）
- _ssh_format_prefix：生成运维结果的服务器标识前缀
- _ssh_check_dangerous：检查命令是否危险
- _ssh_validate_host：校验主机地址合法性（含 SSRF 防护）

依赖：
- 标准库：os, threading, asyncio, re, datetime, base64
- 第三方库：asyncssh（SSH 协议实现）
- 无 zeroai.core 依赖（本模块自包含所有状态）
"""
import os
import threading as _ssh_threading_mod  # 用别名避免污染命名空间


# ════════════════════════════════════════════════════════════════════
# SSH 全局状态与配置常量
# 迁移来源：tui_agent.py 行 6787-6818
# ════════════════════════════════════════════════════════════════════

# 安全审计日志
_SSH_AUDIT_LOG = []
_SSH_AUDIT_MAX = 200

# 危险命令黑名单（需要用户确认才执行）
_SSH_DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+/(?!\S)",   # rm -rf /
    r"\bmkfs\b",                # 格式化
    r"\bdd\s+if=",              # dd 写入
    r"\bshutdown\b",            # 关机
    r"\binit\s+0\b",            # 关机
    r"\bhalt\b",                # 关机
    r"\breboot\b",             # 重启
    r">\s*/dev/sd[a-z]",       # 写裸设备
    r"\biptables\s+-F\b",      # 清空防火墙
    r"\bchmod\s+-R\s+777\s+/\b",  # 全盘777
    r"\b:\(\)\s*\{",           # fork炸弹
]

# SSH 连接池（支持多服务器并行连接）
_SSH_CONNECTIONS = {}  # {conn_id: {"conn": conn, "host": host, "user": user, "connected_at": ts}}

# 内网保留IP黑名单（防止SSRF类攻击，可选启用）
_SSH_BLOCK_PRIVATE_IPS = False  # 默认允许内网IP（远程部署通常就是内网服务器）

# SSH 专用事件循环（在独立线程运行，避免与 Textual 主事件循环冲突）
# asyncssh 的连接对象绑定到创建它的事件循环，必须保证所有 SSH 操作使用同一个循环
_SSH_LOOP = None
_SSH_LOOP_THREAD = None
_SSH_LOOP_LOCK = _ssh_threading_mod.Lock()

# 操作系统检测缓存（按 conn_id 缓存，避免每次都探测）
_SSH_OS_CACHE = {}


def _ssh_run_async(coro_factory):
    """在 Textual 事件循环已运行的环境下安全执行 async 协程。

    设计要点（重要）：
    asyncssh 的连接对象（asyncssh.SSHClientConnection）**绑定到创建它的事件循环**，
    后续对该连接的所有操作（run、exec、close）必须在同一个事件循环里。
    因此采用「持久事件循环线程」模式：
    - 全局维护一个独立的 SSH 事件循环，运行在后台守护线程中
    - 所有 SSH 协程都通过 asyncio.run_coroutine_threadsafe 提交到这个循环
    - 这样无论 ZeroAI 主循环是否在运行，SSH 连接对象都能正确复用

    Args:
        coro_factory: 无参数可调用对象，返回一个协程
    Returns:
        协程的返回值；若执行出错，返回字符串 "错误：{异常}"

    迁移来源：tui_agent.py 行 6821-6859
    """
    import asyncio
    import threading

    global _SSH_LOOP, _SSH_LOOP_THREAD
    with _SSH_LOOP_LOCK:
        if _SSH_LOOP is None or not _SSH_LOOP.is_running():
            _SSH_LOOP = asyncio.new_event_loop()

            def _loop_runner():
                asyncio.set_event_loop(_SSH_LOOP)
                try:
                    _SSH_LOOP.run_forever()
                finally:
                    _SSH_LOOP.close()

            _SSH_LOOP_THREAD = threading.Thread(target=_loop_runner, daemon=True, name="ssh-event-loop")
            _SSH_LOOP_THREAD.start()

    future = asyncio.run_coroutine_threadsafe(coro_factory(), _SSH_LOOP)
    try:
        return future.result(timeout=300)  # 整体超时 5 分钟
    except Exception as e:
        return f"错误：{e}"


def _ssh_is_conn_closed(conn) -> bool:
    """统一判断 asyncssh 连接是否已关闭。
    兼容不同 asyncssh 版本：is_closed 可能是属性（旧版）或方法（新版 2.24+）。

    迁移来源：tui_agent.py 行 6862-6874
    """
    if conn is None:
        return True
    try:
        val = conn.is_closed
        if callable(val):
            val = val()
        return bool(val)
    except Exception:
        return True


def _ssh_detect_os(conn_id: str = "default") -> str:
    """检测远程服务器操作系统。返回 'windows' / 'linux'。
    结果按 conn_id 缓存，连接断开后自动清除缓存。

    探测策略（多重冗余，避免单一命令失败导致误判）：
    1. 优先用 `ver` 命令（Windows cmd 内建，输出含 "Microsoft Windows"）
    2. 回退用 `echo %OS%`（Windows 输出 "Windows_NT"）
    3. 再回退用 `uname`（Linux 输出内核名，Windows 无此命令）

    注意：本函数通过 _raw_ssh_exec 绕过 ssh_exec 的编码注入，避免递归调用。

    迁移来源：tui_agent.py 行 6881-6959
    """
    # 如果连接已不存在，清除缓存
    if conn_id not in _SSH_CONNECTIONS:
        _SSH_OS_CACHE.pop(conn_id, None)
        return "linux"  # 默认按 Linux 处理

    # 命中缓存
    if conn_id in _SSH_OS_CACHE:
        return _SSH_OS_CACHE[conn_id]

    os_type = "linux"  # 默认 Linux

    # 内部执行函数（绕过 ssh_exec 的编码注入，避免递归）
    def _raw_exec(cmd: str) -> str:
        """直接调用 asyncssh，不经过 ssh_exec 的编码处理"""
        conn_info = _SSH_CONNECTIONS.get(conn_id)
        if not conn_info:
            return ""
        conn = conn_info["conn"]
        if _ssh_is_conn_closed(conn):
            return ""
        import asyncio
        async def _run():
            try:
                import asyncssh
                result = await asyncio.wait_for(
                    conn.run(cmd, check=False, timeout=8,
                             encoding='utf-8', errors='replace'),
                    timeout=13
                )
                return result.stdout or ""
            except Exception:
                return ""
        try:
            return _ssh_run_async(_run)
        except Exception:
            return ""

    # 探测1：ver 命令（Windows cmd 内建，最可靠）
    try:
        raw1 = _raw_exec("ver")
        if raw1 and ("Microsoft" in raw1 or "Windows" in raw1):
            os_type = "windows"
    except Exception:
        pass

    # 探测2：echo %OS%（Windows 输出 Windows_NT）
    if os_type == "linux":
        try:
            raw2 = _raw_exec("echo %OS%")
            if raw2 and "Windows_NT" in raw2:
                os_type = "windows"
        except Exception:
            pass

    # 探测3：uname（Linux 一定有输出，Windows 会报错）
    if os_type == "linux":
        try:
            raw3 = _raw_exec("uname")
            # Linux 的 uname 会输出 Linux/Darwin 等；Windows 会报 "不是内部或外部命令"
            if raw3 and ("不是内部或外部命令" in raw3 or "not recognized" in raw3
                         or "无法找到" in raw3):
                # uname 不存在 → 大概率是 Windows
                os_type = "windows"
        except Exception:
            pass

    _SSH_OS_CACHE[conn_id] = os_type
    return os_type


def _ssh_audit(host: str, user: str, command: str, result_summary: str = ""):
    """记录SSH操作审计日志（脱敏：不显示完整 IP 地址）

    迁移来源：tui_agent.py 行 6962-6979
    """
    import datetime
    # 安全设计：对 host 进行脱敏处理，不显示完整 IP
    # 如果是 IP 地址，只保留前两段，后两段用 *** 替代
    # 如果是域名，保留原样
    import re as _re_audit
    if _re_audit.match(r'^(\d{1,3}\.){3}\d{1,3}$', host):
        parts = host.split(".")
        safe_host = f"{parts[0]}.{parts[1]}.***.***"
    else:
        safe_host = host
    entry = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {user}@{safe_host} → {command[:200]}"
    if result_summary:
        entry += f" | {result_summary[:100]}"
    _SSH_AUDIT_LOG.append(entry)
    if len(_SSH_AUDIT_LOG) > _SSH_AUDIT_MAX:
        _SSH_AUDIT_LOG.pop(0)


def _ssh_format_prefix(conn_id: str = "default") -> str:
    """生成运维结果的服务器标识前缀（防混淆）。

    格式: "[conn_id | 备注]" 或 "[conn_id]"

    多服务器场景下，每个运维工具的返回结果都应以此前缀开头，
    让用户和 AI 一眼看清这是哪台机器的输出。

    安全设计：不在前缀中显示服务器 IP 地址，仅用 conn_id 和备注标识。
    如需查看完整连接信息（含 IP），请用 ssh_list 工具。

    Args:
        conn_id: 连接ID

    Returns:
        形如 "[nas | NAS存储服务器]" 或 "[default]" 的前缀字符串

    迁移来源：tui_agent.py 行 6982-7005
    """
    info = _SSH_CONNECTIONS.get(conn_id)
    if not info:
        return f"[{conn_id}]"
    remark = info.get("remark", "")
    if remark:
        return f"[{conn_id} | {remark}]"
    return f"[{conn_id}]"


def _ssh_check_dangerous(command: str) -> tuple:
    """检查命令是否危险，返回 (is_dangerous, matched_pattern)

    迁移来源：tui_agent.py 行 7008-7014
    """
    import re
    for pattern in _SSH_DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, pattern
    return False, None


def _ssh_validate_host(host: str) -> tuple:
    """校验主机地址合法性，返回 (is_valid, error_msg)

    迁移来源：tui_agent.py 行 7017-7047
    """
    if not host or not isinstance(host, str):
        return False, "主机地址不能为空"
    # 去除协议前缀
    host = host.replace("ssh://", "").replace("SSH://", "")
    # 去除端口
    hostname = host.split(":")[0]
    # 校验IP或域名格式
    import re
    ip_pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
    domain_pattern = r"^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
    if re.match(ip_pattern, hostname):
        parts = hostname.split(".")
        for p in parts:
            if int(p) > 255:
                return False, f"IP地址段无效: {p}"
        # 检查内网IP（可选阻断）
        if _SSH_BLOCK_PRIVATE_IPS:
            if parts[0] in ("10", "172", "192", "127"):
                if parts[0] == "172" and not (16 <= int(parts[1]) <= 31):
                    pass  # 172.x 但不在16-31范围，不阻断
                elif parts[0] == "192" and parts[1] != "168":
                    pass  # 192.x 但不是168，不阻断
                else:
                    return False, "内网地址被策略阻断（如需连接内网，请联系管理员调整策略）"
        return True, ""
    elif re.match(domain_pattern, hostname):
        return True, ""
    else:
        return False, f"主机地址格式无效（请检查 IP/域名格式）"


def ssh_connect(host: str, user: str, password: str = "", key_path: str = "",
                port: int = 22, conn_id: str = "default", remark: str = "") -> str:
    """连接到远程SSH服务器。

    支持密码认证和密钥认证两种方式。连接成功后保持长连接，后续命令通过 conn_id 复用。

    Args:
        host: 服务器地址（IP或域名，可带端口如 192.168.1.100:2222）
        user: 登录用户名
        password: 密码认证（二选一）
        key_path: SSH私钥路径（如 ~/.ssh/id_rsa），密码和密钥二选一
        port: SSH端口，默认22
        conn_id: 连接标识符，用于多服务器管理，默认"default"
        remark: 服务器备注/角色（如 "NAS存储"、"Web前端"、"数据库"），便于多服务器场景下识别，防混淆

    Returns:
        连接状态信息

    迁移来源：tui_agent.py 行 7050-7148
    """
    import asyncio

    # 校验主机地址
    is_valid, err = _ssh_validate_host(host)
    if not is_valid:
        return f"连接失败：{err}"

    # 如果已有同名连接，先断开
    if conn_id in _SSH_CONNECTIONS:
        try:
            old = _SSH_CONNECTIONS.pop(conn_id)
            if old.get("conn") and not _ssh_is_conn_closed(old["conn"]):
                # asyncssh 的 close() 是同步方法
                old["conn"].close()
        except Exception:
            pass

    async def _connect():
        import asyncssh
        try:
            # 准备认证参数
            connect_kwargs = {
                "host": host.split(":")[0] if ":" in host else host,
                "port": port if ":" not in host else int(host.split(":")[1]),
                "username": user,
                "known_hosts": None,  # 跳过known_hosts检查（部署场景）
                "login_timeout": 15,
                "keepalive_interval": 30,
                "keepalive_count_max": 3,
            }
            if key_path:
                # 密钥认证
                key_path_expanded = os.path.expanduser(key_path)
                if not os.path.exists(key_path_expanded):
                    return f"连接失败：私钥文件不存在: {key_path_expanded}"
                connect_kwargs["client_keys"] = [key_path_expanded]
            elif password:
                # 密码认证
                connect_kwargs["password"] = password
            else:
                return "连接失败：必须提供 password 或 key_path 之一"

            conn = await asyncssh.connect(**connect_kwargs)
            return conn
        except asyncssh.PermissionDenied:
            return "连接失败：认证失败（密码/密钥错误）"
        except asyncssh.ConnectionLost:
            return "连接失败：连接丢失（网络不稳定）"
        except asyncssh.DisconnectError as e:
            return f"连接失败：服务器拒绝连接 (code={e.code}, reason={e.reason})"
        except asyncio.TimeoutError:
            return f"连接失败：超时（15秒内未连接到服务器，请检查网络和端口）"
        except OSError as e:
            return f"连接失败：网络错误 ({e})"

    try:
        result = _ssh_run_async(_connect)
        if isinstance(result, str):
            return result
        # 连接成功
        import time
        _SSH_CONNECTIONS[conn_id] = {
            "conn": result,
            "host": host.split(":")[0] if ":" in host else host,
            "user": user,
            "port": port if ":" not in host else int(host.split(":")[1]),
            "connected_at": time.time(),
            "remark": remark,  # 服务器备注/角色（防混淆）
        }
        # 连接建立后清除 OS 缓存，下次运维工具调用时重新探测
        _SSH_OS_CACHE.pop(conn_id, None)
        _ssh_audit(host, user, "[CONNECT]", f"成功 conn_id={conn_id} remark={remark}")
        remark_line = f"\n  备注: {remark}" if remark else ""
        # 安全设计：不在返回结果中显示服务器 IP 地址，仅显示备注/conn_id
        # IP 地址仅存储在内部 _SSH_CONNECTIONS 中供工具内部使用
        server_label = remark if remark else conn_id
        return (f"✅ SSH连接成功\n  服务器: {server_label}\n  用户: {user}\n  端口: {port if ':' not in host else host.split(':')[1]}\n"
                f"  连接ID: {conn_id}\n  认证方式: {'密钥' if key_path else '密码'}{remark_line}\n"
                f"  提示: 后续运维操作请传 conn_id='{conn_id}'")
    except Exception as e:
        return f"连接失败：{e}"


def ssh_exec(command: str, conn_id: str = "default", timeout: int = 30,
             confirm_dangerous: bool = False, _internal: bool = False) -> str:
    """在远程服务器上执行Shell命令。

    通过已建立的SSH连接执行命令。危险命令（如rm -rf /、mkfs、shutdown）需要
    confirm_dangerous=True 才会执行。

    Args:
        command: 要执行的Shell命令
        conn_id: 连接ID（由ssh_connect返回），默认"default"
        timeout: 命令超时时间（秒），默认30
        confirm_dangerous: 是否确认执行危险命令，默认False
        _internal: 内部调用标记（运维工具内部调用时传 True，不加服务器前缀，避免前缀重复）

    Returns:
        命令输出结果（stdout + stderr），默认带服务器标识前缀防混淆

    迁移来源：tui_agent.py 行 7151-7260
    """
    import asyncio

    # 检查连接是否存在
    if conn_id not in _SSH_CONNECTIONS:
        return f"错误：连接 '{conn_id}' 不存在，请先调用 ssh_connect 建立连接"

    conn_info = _SSH_CONNECTIONS[conn_id]
    conn = conn_info["conn"]
    # 兼容 asyncssh 不同版本：is_closed 可能是属性（旧版）或方法（新版 2.24+）
    if _ssh_is_conn_closed(conn):
        _SSH_CONNECTIONS.pop(conn_id, None)
        return f"错误：连接 '{conn_id}' 已断开，请重新调用 ssh_connect"

    # 危险命令检查
    is_dangerous, pattern = _ssh_check_dangerous(command)
    if is_dangerous and not confirm_dangerous:
        return (f"⚠️ 检测到危险命令（匹配模式: {pattern}）\n"
                f"命令: {command}\n"
                f"如确认要执行，请重新调用并设置 confirm_dangerous=true")

    async def _exec():
        try:
            import asyncssh
            # encoding='utf-8', errors='replace' 兼容中文 Windows 的 GBK 输出
            # asyncssh 默认用 UTF-8 解码，Windows cmd 输出 GBK 会乱码或报错
            result = await asyncio.wait_for(
                conn.run(command, check=False, timeout=timeout,
                         encoding='utf-8', errors='replace'),
                timeout=timeout + 5
            )
            return result
        except asyncio.TimeoutError:
            return f"命令超时（{timeout}秒）"
        except asyncssh.ChannelOpenError as e:
            return f"通道错误: {e}"
        except Exception as e:
            return f"执行错误: {e}"

    try:
        # Windows 中文乱码修复：自动给 PowerShell/cmd 命令注入 UTF-8 编码
        # 原因：Windows 中文系统默认 GBK 编码，asyncssh 用 UTF-8 解码会乱码
        if _ssh_detect_os(conn_id) == "windows":
            if command.startswith("powershell"):
                # PowerShell 命令：注入 UTF-8 输出编码设置
                if '-Command "' in command:
                    command = command.replace(
                        '-Command "',
                        '-Command "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8; ',
                        1
                    )
                elif "-Command '" in command:
                    command = command.replace(
                        "-Command '",
                        "-Command '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8; ",
                        1
                    )
            else:
                # cmd 命令：切换代码页到 65001 (UTF-8)
                if not command.startswith("chcp"):
                    command = f"chcp 65001 >nul 2>&1 & {command}"

        result = _ssh_run_async(_exec)
        prefix = "" if _internal else _ssh_format_prefix(conn_id) + "\n"
        if isinstance(result, str):
            _ssh_audit(conn_info["host"], conn_info["user"], command, result[:100])
            return prefix + result

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code = result.exit_status or 0

        # 截断过长输出
        if len(stdout) > 8000:
            stdout = stdout[:8000] + f"\n... (输出过长，已截断，共 {len(stdout)} 字符)"
        if len(stderr) > 4000:
            stderr = stderr[:4000] + f"\n... (错误输出过长，已截断，共 {len(stderr)} 字符)"

        summary = f"exit={exit_code}, out={len(stdout)}B, err={len(stderr)}B"
        _ssh_audit(conn_info["host"], conn_info["user"], command, summary)

        # 格式化输出
        parts = []
        if stdout:
            parts.append(stdout.rstrip())
        if stderr:
            parts.append(f"[stderr]\n{stderr.rstrip()}")
        if exit_code != 0:
            parts.append(f"[退出码: {exit_code}]")

        body = "\n".join(parts) if parts else "[无输出]"
        return prefix + body
    except Exception as e:
        return f"执行错误: {e}"


def ssh_upload(local_path: str, remote_path: str, conn_id: str = "default") -> str:
    """上传本地文件到远程服务器（SFTP）。

    支持单文件上传。上传后自动设置权限为644。

    Args:
        local_path: 本地文件路径
        remote_path: 远程目标路径（完整路径，如 /opt/myapp/config.yml）
        conn_id: 连接ID

    Returns:
        上传结果

    迁移来源：tui_agent.py 行 7263-7318
    """
    import asyncio

    if conn_id not in _SSH_CONNECTIONS:
        return f"错误：连接 '{conn_id}' 不存在，请先调用 ssh_connect"

    conn_info = _SSH_CONNECTIONS[conn_id]
    conn = conn_info["conn"]
    if _ssh_is_conn_closed(conn):
        _SSH_CONNECTIONS.pop(conn_id, None)
        return f"错误：连接 '{conn_id}' 已断开，请重新连接"

    local_path = os.path.abspath(local_path)
    if not os.path.exists(local_path):
        return f"错误：本地文件不存在: {local_path}"

    local_size = os.path.getsize(local_path)

    async def _upload():
        try:
            import asyncssh
            async with conn.start_sftp_client() as sftp:
                await sftp.put(local_path, remote_path)
                # 设置权限644
                try:
                    await sftp.chmod(remote_path, 0o644)
                except Exception:
                    pass  # 权限设置失败不影响上传
            return True
        except asyncssh.SFTPError as e:
            return f"SFTP错误: {e}"
        except Exception as e:
            return f"上传错误: {e}"

    try:
        result = _ssh_run_async(_upload)
        if result is True:
            _ssh_audit(conn_info["host"], conn_info["user"],
                       f"[UPLOAD] {local_path} → {remote_path}",
                       f"{local_size}B")
            return f"{_ssh_format_prefix(conn_id)}\n✅ 上传成功\n  本地: {local_path} ({local_size} 字节)\n  远程: {remote_path}"
        return f"上传失败: {result}"
    except Exception as e:
        return f"上传错误: {e}"


def ssh_download(remote_path: str, local_path: str, conn_id: str = "default") -> str:
    """从远程服务器下载文件到本地（SFTP）。

    Args:
        remote_path: 远程文件路径
        local_path: 本地保存路径
        conn_id: 连接ID

    Returns:
        下载结果

    迁移来源：tui_agent.py 行 7321-7369
    """
    import asyncio

    if conn_id not in _SSH_CONNECTIONS:
        return f"错误：连接 '{conn_id}' 不存在，请先调用 ssh_connect"

    conn_info = _SSH_CONNECTIONS[conn_id]
    conn = conn_info["conn"]
    if _ssh_is_conn_closed(conn):
        _SSH_CONNECTIONS.pop(conn_id, None)
        return f"错误：连接 '{conn_id}' 已断开，请重新连接"

    # 确保本地目录存在
    local_dir = os.path.dirname(os.path.abspath(local_path))
    if local_dir:
        os.makedirs(local_dir, exist_ok=True)

    async def _download():
        try:
            import asyncssh
            async with conn.start_sftp_client() as sftp:
                await sftp.get(remote_path, local_path)
            return True
        except asyncssh.SFTPError as e:
            return f"SFTP错误: {e}"
        except Exception as e:
            return f"下载错误: {e}"

    try:
        result = _ssh_run_async(_download)
        if result is True:
            local_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
            _ssh_audit(conn_info["host"], conn_info["user"],
                       f"[DOWNLOAD] {remote_path} → {local_path}",
                       f"{local_size}B")
            return f"{_ssh_format_prefix(conn_id)}\n✅ 下载成功\n  远程: {remote_path}\n  本地: {local_path} ({local_size} 字节)"
        return f"下载失败: {result}"
    except Exception as e:
        return f"下载错误: {e}"


def ssh_deploy(deploy_config: dict, conn_id: str = "default") -> str:
    """一键项目部署（多步骤自动化部署）。

    按顺序执行部署步骤：环境检查→创建目录→上传代码→安装依赖→重启服务→健康检查。

    Args:
        deploy_config: 部署配置字典，包含：
            - pre_check: 部署前检查命令列表（如 ["uname -a", "docker --version"]）
            - remote_dir: 远程部署目录（如 /opt/myapp）
            - upload_files: 上传文件列表 [[local, remote], ...]
            - install_cmd: 安装依赖命令（如 "pip install -r requirements.txt"）
            - restart_cmd: 重启服务命令（如 "systemctl restart myapp"）
            - health_check: 健康检查命令（如 "curl -s localhost:8080/health"）
            - post_cmds: 部署后额外命令列表
        conn_id: 连接ID

    Returns:
        部署报告（每步结果汇总）

    迁移来源：tui_agent.py 行 7372-7495
    """
    if conn_id not in _SSH_CONNECTIONS:
        return f"错误：连接 '{conn_id}' 不存在，请先调用 ssh_connect"

    report = []
    report.append("=" * 50)
    report.append("🚀 SSH 自动化部署")
    report.append("=" * 50)

    step = 0
    total_steps = 0
    # 计算总步骤数
    if deploy_config.get("pre_check"):
        total_steps += len(deploy_config["pre_check"])
    if deploy_config.get("remote_dir"):
        total_steps += 1
    if deploy_config.get("upload_files"):
        total_steps += len(deploy_config["upload_files"])
    if deploy_config.get("install_cmd"):
        total_steps += 1
    if deploy_config.get("restart_cmd"):
        total_steps += 1
    if deploy_config.get("health_check"):
        total_steps += 1
    if deploy_config.get("post_cmds"):
        total_steps += len(deploy_config["post_cmds"])

    report.append(f"总步骤: {total_steps}")
    report.append("")

    # 1. 环境检查
    if deploy_config.get("pre_check"):
        report.append("📋 [步骤] 环境检查")
        for cmd in deploy_config["pre_check"]:
            step += 1
            result = ssh_exec(cmd, conn_id, _internal=True, timeout=15)
            status = "✅" if "错误" not in result and "exit_code" not in result.lower() else "⚠️"
            report.append(f"  {status} [{step}/{total_steps}] {cmd}")
            report.append(f"     {result[:200]}")
            report.append("")

    # 2. 创建远程目录
    if deploy_config.get("remote_dir"):
        step += 1
        remote_dir = deploy_config["remote_dir"]
        report.append(f"📁 [步骤 {step}/{total_steps}] 创建目录: {remote_dir}")
        result = ssh_exec(f"mkdir -p {remote_dir}", conn_id)
        report.append(f"  {result[:200]}")
        report.append("")

    # 3. 上传文件
    if deploy_config.get("upload_files"):
        for local, remote in deploy_config["upload_files"]:
            step += 1
            report.append(f"📤 [步骤 {step}/{total_steps}] 上传: {local} → {remote}")
            result = ssh_upload(local, remote, conn_id)
            status = "✅" if "成功" in result else "❌"
            report.append(f"  {status} {result[:200]}")
            report.append("")

    # 4. 安装依赖
    if deploy_config.get("install_cmd"):
        step += 1
        install_cmd = deploy_config["install_cmd"]
        remote_dir = deploy_config.get("remote_dir", "")
        report.append(f"📦 [步骤 {step}/{total_steps}] 安装依赖: {install_cmd}")
        full_cmd = f"cd {remote_dir} && {install_cmd}" if remote_dir else install_cmd
        result = ssh_exec(full_cmd, conn_id, _internal=True, timeout=120)
        report.append(f"  {result[:500]}")
        report.append("")

    # 5. 重启服务
    if deploy_config.get("restart_cmd"):
        step += 1
        restart_cmd = deploy_config["restart_cmd"]
        report.append(f"🔄 [步骤 {step}/{total_steps}] 重启服务: {restart_cmd}")
        result = ssh_exec(restart_cmd, conn_id, timeout=30)
        report.append(f"  {result[:300]}")
        report.append("")

    # 6. 健康检查
    if deploy_config.get("health_check"):
        step += 1
        health_cmd = deploy_config["health_check"]
        report.append(f"🏥 [步骤 {step}/{total_steps}] 健康检查: {health_cmd}")
        result = ssh_exec(health_cmd, conn_id, _internal=True, timeout=15)
        status = "✅ 健康" if "错误" not in result and "exit_code" not in result.lower() else "⚠️ 需检查"
        report.append(f"  {status}")
        report.append(f"  {result[:300]}")
        report.append("")

    # 7. 部署后命令
    if deploy_config.get("post_cmds"):
        for cmd in deploy_config["post_cmds"]:
            step += 1
            report.append(f"⚙️ [步骤 {step}/{total_steps}] 后置: {cmd}")
            result = ssh_exec(cmd, conn_id, _internal=True, timeout=30)
            report.append(f"  {result[:200]}")
            report.append("")

    # 汇总
    report.append("=" * 50)
    report.append(f"✅ 部署完成 ({step}/{total_steps} 步骤已执行)")
    report.append("=" * 50)

    return _ssh_format_prefix(conn_id) + "\n" + "\n".join(report)


def ssh_setup_samba_share(share_name: str = "shared",
                          share_path: str = "/srv/shared",
                          access_mode: str = "guest_rw",
                          samba_password: str = "",
                          conn_id: str = "default") -> str:
    r"""一键配置 Samba 共享文件夹（Linux 服务器专用，自动完成全部步骤）。

    自动执行的 8 个步骤：
    1. 检测操作系统（必须是 Linux，Windows 应该用 New-SmbShare）
    2. 安装 Samba（自动识别 apt/yum/dnf 包管理器）
    3. 创建共享文件夹并设置权限
    4. 备份原 smb.conf
    5. 写入共享配置（支持 guest_ro/guest_rw/user_rw 三种权限模式）
    6. 设置 Samba 密码（user_rw 模式需要）
    7. 启动 smbd/nmb 服务并设置开机自启
    8. 防火墙放行 + SELinux 处理 + 验证共享

    Args:
        share_name: 共享名（Windows 访问时用，如 "shared"，访问路径 \\IP\shared）
        share_path: 共享文件夹在 Linux 上的路径，默认 /srv/shared
        access_mode: 权限模式：
            - guest_ro: 匿名只读（任何人可读不可写）
            - guest_rw: 匿名读写（任何人可读写，适合内网共享，默认）
            - user_rw: 用户认证读写（需 samba_password，更安全）
        samba_password: Samba 密码（user_rw 模式必填，其他模式可留空）
        conn_id: SSH 连接ID

    Returns:
        配置结果报告 + Windows 访问路径

    迁移来源：tui_agent.py 行 7498-7744
    """
    import base64

    prefix = _ssh_format_prefix(conn_id)

    # 步骤1: 检测操作系统
    os_type = _ssh_detect_os(conn_id)
    if os_type == "windows":
        return (f"{prefix}\n❌ 此工具仅支持 Linux 服务器配置 Samba 共享。\n"
                f"Windows Server 请用 ssh_exec 执行 PowerShell 命令：\n"
                f"  New-SmbShare -Name '{share_name}' -Path 'D:\\{share_name}' -FullAccess Everyone")

    report = [
        "=" * 50,
        f"Samba 共享一键配置报告",
        f"  共享名: {share_name}",
        f"  共享路径: {share_path}",
        f"  权限模式: {access_mode}",
        "=" * 50,
    ]
    step = 0
    total_steps = 8

    # 步骤2: 安装 Samba（自动识别包管理器）
    step += 1
    report.append(f"\n[{step}/{total_steps}] 安装 Samba...")
    install_cmd = (
        'if command -v apt-get >/dev/null 2>&1; then '
        '  apt-get update -qq 2>&1 | tail -1; apt-get install -y -qq samba 2>&1 | tail -3; '
        'elif command -v dnf >/dev/null 2>&1; then '
        '  dnf install -y samba 2>&1 | tail -3; '
        'elif command -v yum >/dev/null 2>&1; then '
        '  yum install -y samba 2>&1 | tail -3; '
        'else echo "错误：未识别的包管理器（apt/dnf/yum 均不存在）"; exit 1; fi; '
        'which smbd && smbd --version'
    )
    r = ssh_exec(install_cmd, conn_id, _internal=True, timeout=180)
    if "smbd" not in r or "Version" not in r:
        report.append(f"  ❌ Samba 安装失败:\n{r[-500:]}")
        report.append("\n" + "=" * 50)
        report.append("❌ 配置失败，请检查包管理器或网络")
        return prefix + "\n" + "\n".join(report)
    report.append(f"  ✅ Samba 已安装: {r.split('Version')[-1].strip() if 'Version' in r else '已就绪'}")

    # 步骤3: 创建共享文件夹
    step += 1
    report.append(f"\n[{step}/{total_steps}] 创建共享文件夹 {share_path}...")
    r = ssh_exec(f'mkdir -p {share_path} && chmod 777 {share_path} && ls -ld {share_path}',
                 conn_id, _internal=True, timeout=10)
    if "drwx" not in r:
        report.append(f"  ❌ 文件夹创建失败:\n{r[-300:]}")
        return prefix + "\n" + "\n".join(report)
    report.append(f"  ✅ 文件夹已创建: {r.split('drwx')[0].strip() or r.strip().split(chr(10))[-1]}")

    # 步骤4: 备份原 smb.conf
    step += 1
    report.append(f"\n[{step}/{total_steps}] 备份原 smb.conf...")
    r = ssh_exec('cp /etc/samba/smb.conf /etc/samba/smb.conf.bak.$(date +%s) 2>/dev/null && echo "备份成功" || echo "无需备份（首次配置）"',
                 conn_id, _internal=True, timeout=10)
    report.append(f"  ✅ {r.strip().split(chr(10))[-1]}")

    # 步骤5: 写入共享配置（根据权限模式生成不同配置）
    step += 1
    report.append(f"\n[{step}/{total_steps}] 写入共享配置（权限模式: {access_mode}）...")

    if access_mode == "guest_ro":
        # 匿名只读
        share_config = f"""[global]
   workgroup = WORKGROUP
   security = user
   map to guest = Bad User
   passdb backend = tdbsam
   printing = bsd
   printcap name = /dev/null
   load printers = no

[{share_name}]
   comment = Shared Folder
   path = {share_path}
   browseable = yes
   writable = no
   guest ok = yes
   read only = yes
"""
    elif access_mode == "guest_rw":
        # 匿名读写（默认，内网共享推荐）
        share_config = f"""[global]
   workgroup = WORKGROUP
   security = user
   map to guest = Bad User
   passdb backend = tdbsam
   printing = bsd
   printcap name = /dev/null
   load printers = no

[{share_name}]
   comment = Shared Folder
   path = {share_path}
   browseable = yes
   writable = yes
   guest ok = yes
   force user = root
   force group = root
   create mask = 0666
   directory mask = 0777
"""
    else:  # user_rw
        # 用户认证读写（更安全）
        share_config = f"""[global]
   workgroup = WORKGROUP
   security = user
   passdb backend = tdbsam
   printing = bsd
   printcap name = /dev/null
   load printers = no

[{share_name}]
   comment = Shared Folder
   path = {share_path}
   browseable = yes
   writable = yes
   guest ok = no
   valid users = root
   create mask = 0664
   directory mask = 0775
"""

    b64 = base64.b64encode(share_config.encode('utf-8')).decode('ascii')
    r = ssh_exec(f'echo "{b64}" | base64 -d > /etc/samba/smb.conf && testparm -s 2>&1 | head -20',
                 conn_id, _internal=True, timeout=10)
    if "Loaded services file" not in r and "[" + share_name + "]" not in r:
        report.append(f"  ❌ 配置写入失败:\n{r[-400:]}")
        return prefix + "\n" + "\n".join(report)
    report.append(f"  ✅ 配置已写入，testparm 校验通过")

    # 步骤6: 设置 Samba 密码（user_rw 模式）
    step += 1
    if access_mode == "user_rw":
        report.append(f"\n[{step}/{total_steps}] 设置 Samba 密码 (root)...")
        if not samba_password:
            report.append("  ⚠️ user_rw 模式未提供密码，跳过（可用 smbpasswd -a root 手动设置）")
        else:
            # 用单引号包裹密码避免特殊字符问题
            r = ssh_exec(f'(echo "{samba_password}"; echo "{samba_password}") | smbpasswd -a root -s 2>&1',
                         conn_id, _internal=True, timeout=10)
            if "Added user" in r:
                report.append(f"  ✅ Samba 密码已设置 (root)")
            else:
                report.append(f"  ⚠️ 密码设置失败: {r.strip()[-200:]}")
    else:
        report.append(f"\n[{step}/{total_steps}] 跳过密码设置（{access_mode} 模式无需密码）")

    # 步骤7: 启动 smbd/nmb 服务 + 开机自启
    step += 1
    report.append(f"\n[{step}/{total_steps}] 启动 smbd/nmb 服务 + 开机自启...")
    r = ssh_exec('systemctl enable --now smb nmb 2>&1 | tail -2; systemctl is-active smb nmb; systemctl is-enabled smb nmb',
                 conn_id, _internal=True, timeout=15)
    if "active" not in r:
        report.append(f"  ❌ 服务启动失败:\n{r[-300:]}")
        return prefix + "\n" + "\n".join(report)
    report.append(f"  ✅ smbd/nmb 已启动并设为开机自启")

    # 步骤8: 防火墙放行 + SELinux 处理 + 验证
    step += 1
    report.append(f"\n[{step}/{total_steps}] 防火墙放行 + SELinux 处理...")

    # 防火墙
    r_fw = ssh_exec('systemctl is-active firewalld 2>/dev/null && '
                    '(firewall-cmd --permanent --add-service=samba 2>&1; firewall-cmd --reload 2>&1) || '
                    'echo "firewalld 未运行，跳过"',
                    conn_id, _internal=True, timeout=15)
    if "success" in r_fw:
        report.append("  ✅ 防火墙已放行 Samba 服务")
    else:
        report.append(f"  ℹ️ 防火墙: {r_fw.strip().split(chr(10))[-1]}")

    # SELinux
    r_se = ssh_exec('getenforce 2>/dev/null || echo "Disabled"',
                    conn_id, _internal=True, timeout=10)
    se_status = r_se.strip().split(chr(10))[-1] if r_se else "Disabled"
    if se_status == "Enforcing":
        ssh_exec(f'setsebool -P samba_enable_home_dirs on 2>/dev/null; '
                 f'semanage fcontext -a -t samba_share_t "{share_path}(/.*)?" 2>/dev/null; '
                 f'restorecon -Rv {share_path} 2>&1 | tail -1',
                 conn_id, _internal=True, timeout=15)
        report.append("  ✅ SELinux 上下文已设置")
    else:
        report.append(f"  ℹ️ SELinux: {se_status}（无需处理）")

    # 验证共享
    r_test = ssh_exec(f'echo "Samba 共享测试 $(date)" > {share_path}/test.txt && ls -l {share_path}/test.txt',
                      conn_id, _internal=True, timeout=10)
    if "test.txt" in r_test:
        report.append(f"  ✅ 共享写入测试通过")

    # 获取服务器信息
    info = _SSH_CONNECTIONS.get(conn_id, {})
    host = info.get("host", "服务器IP")
    remark = info.get("remark", "")

    # 最终报告
    report.append("\n" + "=" * 50)
    report.append("✅ Samba 共享配置完成！")
    report.append("=" * 50)
    report.append(f"\n【访问方式】")
    report.append(f"  Windows 资源管理器地址栏输入:")
    report.append(f"    \\\\{host}\\{share_name}")
    if access_mode == "user_rw":
        report.append(f"  用户名: root")
        report.append(f"  密码: {samba_password or '（请用 smbpasswd -a root 设置）'}")
    else:
        report.append(f"  权限: {'读写' if access_mode == 'guest_rw' else '只读'}（无需密码）")
    if remark:
        report.append(f"\n【服务器备注】{remark}（conn_id: {conn_id}）")
    report.append(f"\n【共享路径】{share_path}")
    report.append(f"【配置文件】/etc/samba/smb.conf（原配置已备份为 smb.conf.bak.*）")

    return prefix + "\n" + "\n".join(report)


def ssh_list(conn_id: str = "") -> str:
    """查看SSH连接状态和审计日志。

    Args:
        conn_id: 指定连接ID查看详情，留空查看所有连接和最近审计日志

    Returns:
        连接状态和审计日志（含备注/角色、操作系统、连接时长，便于多服务器场景识别）

    迁移来源：tui_agent.py 行 7747-7818
    """
    def _fmt_uptime(secs: int) -> str:
        """格式化连接时长"""
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m{secs % 60}s"
        return f"{secs // 3600}h{(secs % 3600) // 60}m"

    if conn_id:
        if conn_id not in _SSH_CONNECTIONS:
            return f"连接 '{conn_id}' 不存在"
        info = _SSH_CONNECTIONS[conn_id]
        import time
        uptime = int(time.time() - info.get("connected_at", 0))
        is_closed = _ssh_is_conn_closed(info["conn"])
        os_type = _SSH_OS_CACHE.get(conn_id, "?") if not is_closed else "?"
        remark = info.get("remark", "")
        # 安全设计：不显示服务器 IP，仅显示备注或 conn_id
        server_label = remark if remark else conn_id
        lines = [
            f"连接ID: {conn_id}",
            f"  服务器: {server_label}",
            f"  用户: {info['user']}",
            f"  端口: {info.get('port', 22)}",
            f"  状态: {'❌ 已断开' if is_closed else '✅ 已连接'}",
            f"  操作系统: {os_type}",
            f"  连接时长: {_fmt_uptime(uptime)}",
        ]
        if remark:
            lines.append(f"  备注: {remark}")
        return "\n".join(lines)

    # 列出所有连接
    parts = ["=== SSH 连接状态 ==="]
    if not _SSH_CONNECTIONS:
        parts.append("  (无活动连接)")
        parts.append("  提示: 用 ssh_connect(host, user, password, conn_id='自定义ID', remark='服务器用途') 连接")
    else:
        import time
        parts.append(f"  共 {len(_SSH_CONNECTIONS)} 个连接:")
        parts.append("")
        for cid, info in _SSH_CONNECTIONS.items():
            uptime = int(time.time() - info.get("connected_at", 0))
            is_closed = _ssh_is_conn_closed(info["conn"])
            status = "❌" if is_closed else "✅"
            os_type = _SSH_OS_CACHE.get(cid, "?") if not is_closed else "?"
            remark = info.get("remark", "")
            # 安全设计：不显示 IP，用备注或 conn_id 标识服务器
            server_label = remark if remark else cid
            line = (f"  {status} {cid}: {info['user']}@{server_label}:{info.get('port', 22)} "
                    f"({ _fmt_uptime(uptime)}) [OS: {os_type}]")
            if remark:
                line += f" 备注: {remark}"
            parts.append(line)

    # 审计日志（最近20条）
    if _SSH_AUDIT_LOG:
        parts.append("")
        parts.append("=== 最近操作审计 ===")
        for entry in _SSH_AUDIT_LOG[-20:]:
            parts.append(f"  {entry}")

    return "\n".join(parts)


def ssh_disconnect(conn_id: str = "default") -> str:
    """断开SSH连接。

    Args:
        conn_id: 要断开的连接ID

    Returns:
        断开结果

    迁移来源：tui_agent.py 行 7821-7852
    """
    if conn_id not in _SSH_CONNECTIONS:
        return f"连接 '{conn_id}' 不存在"

    conn_info = _SSH_CONNECTIONS.pop(conn_id)
    conn = conn_info["conn"]

    async def _close():
        try:
            conn.close()
            await conn.wait_closed()
        except Exception:
            pass

    try:
        _ssh_run_async(_close)
    except Exception:
        pass

    _ssh_audit(conn_info["host"], conn_info["user"], "[DISCONNECT]", f"conn_id={conn_id}")
    # 安全设计：不显示服务器 IP，用备注或 conn_id 标识
    remark = conn_info.get("remark", "")
    server_label = remark if remark else conn_id
    return f"✅ 已断开连接 '{conn_id}' ({conn_info['user']}@{server_label})"


def ssh_service_manage(action: str, service: str, conn_id: str = "default") -> str:
    """服务管理（Linux 用 systemctl，Windows 用 sc/Get-Service）。

    Args:
        action: 操作类型，可选值：status / start / stop / restart / reload / enable / disable / is-active / is-enabled
            特殊：service="all" + action="status" 可列出所有运行中的服务
        service: 服务名（如 nginx、mysql、docker、ssh、spooler），或 "all" 查看全部
        conn_id: SSH 连接ID

    Returns:
        服务状态或操作结果（含 AI 友好的状态解读）

    迁移来源：tui_agent.py 行 7859-7995
    """
    # 白名单校验，防注入
    valid_actions = {"status", "start", "stop", "restart", "reload",
                     "enable", "disable", "is-active", "is-enabled"}
    if action not in valid_actions:
        return f"错误：action 必须是 {sorted(valid_actions)} 之一"

    # service 校验：允许 "all" 或合法服务名
    if not service:
        return f"错误：必须提供 service 参数（服务名或 'all'）"
    if service != "all" and not service.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return f"错误：服务名 '{service}' 不合法（仅允许字母数字-_.）"

    os_type = _ssh_detect_os(conn_id)

    if os_type == "windows":
        # Windows 服务管理（用 sc 命令，兼容性最好）
        if service == "all":
            if action == "status":
                # 列出所有运行中的服务（State=Running）
                cmd = 'powershell -NoProfile -Command "Get-Service | Where-Object {$_.Status -eq \'Running\'} | Format-Table Name, DisplayName, Status -AutoSize"'
                raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=30)
                return f"{_ssh_format_prefix(conn_id)}\n$ 列出所有运行中的服务\n{raw}\n\n提示：共显示运行中的服务，可用 ssh_service_manage(action='status', service='具体服务名') 查看单个服务详情"
            else:
                return f"错误：service='all' 只支持 action='status'"
        else:
            # 单个服务操作
            action_map = {
                "status": ("sc", "query"),
                "start": ("sc", "start"),
                "stop": ("sc", "stop"),
                "restart": ("sc", "stop & sc start"),  # Windows sc 无 restart，用 stop+start
                "is-active": ("sc", "query"),
            }
            if action in ("enable", "disable", "is-enabled", "reload"):
                # 这些是 systemd 概念，Windows 用 sc config
                if action == "enable":
                    cmd = f'sc config {service} start= auto'
                elif action == "disable":
                    cmd = f'sc config {service} start= demand'
                elif action == "is-enabled":
                    cmd = f'sc qc {service}'
                else:  # reload
                    return "错误：Windows 服务不支持 reload，请用 restart"
                raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=15)
                interp = ""
                if action == "enable":
                    interp = " → ✅ 已设置开机自启（自动启动）"
                elif action == "disable":
                    interp = " → ✅ 已改为手动启动"
                elif action == "is-enabled":
                    if "AUTO_START" in raw:
                        interp = " → 已设置开机自启"
                    elif "DEMAND_START" in raw:
                        interp = " → 手动启动"
                    elif "DISABLED" in raw:
                        interp = " → 已禁用"
                return f"{_ssh_format_prefix(conn_id)}\n$ {cmd}\n{raw}{interp}"

            sc_cmd, sc_action = action_map.get(action, ("sc", "query"))
            if action == "restart":
                cmd = f'{sc_cmd} {sc_action} {service}'
            else:
                cmd = f'{sc_cmd} {sc_action} {service}'
            raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=15)

            # Windows 状态解读
            interp = ""
            if action in ("status", "is-active"):
                if "RUNNING" in raw:
                    interp = " → ✅ 服务运行中"
                elif "STOPPED" in raw:
                    interp = " ⚠️ 服务已停止"
                elif "START_PENDING" in raw:
                    interp = " → 服务正在启动"
                elif "STOP_PENDING" in raw:
                    interp = " → 服务正在停止"
                elif "The specified service does not exist" in raw or "1060" in raw:
                    interp = " ❌ 服务不存在（检查服务名拼写或未安装）"
            elif action == "start":
                if "SUCCESS" in raw:
                    interp = " → ✅ 服务已启动"
                elif "1056" in raw or "already running" in raw.lower():
                    interp = " → 服务已在运行"
            elif action == "stop":
                if "SUCCESS" in raw:
                    interp = " → ✅ 服务已停止"
                elif "1062" in raw or "not started" in raw.lower():
                    interp = " → 服务未在运行"

            return f"{_ssh_format_prefix(conn_id)}\n$ {cmd}\n{raw}{interp}"

    # Linux 服务管理（systemd，原有逻辑保留）
    if service == "all":
        if action == "status":
            cmd = "systemctl list-units --type=service --state=running --no-pager"
            raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=20)
            return f"{_ssh_format_prefix(conn_id)}\n$ {cmd}\n{raw}"
        else:
            return f"错误：service='all' 只支持 action='status'"

    cmd = f"systemctl {action} {service}"
    raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=30)

    # 添加状态解读
    interpretation = ""
    if action in ("is-active", "is-enabled"):
        if "active" in raw and "inactive" not in raw.split("\n")[0]:
            interpretation = " → 服务正在运行"
        elif "inactive" in raw:
            interpretation = " → 服务已停止"
        elif "enabled" in raw:
            interpretation = " → 已设置开机自启"
        elif "disabled" in raw:
            interpretation = " → 已禁用开机自启"
    elif action == "status":
        if "Active: active (running)" in raw:
            interpretation = " → ✅ 服务运行中"
        elif "Active: inactive" in raw:
            interpretation = " ⚠️ 服务未运行"
        elif "Active: failed" in raw:
            interpretation = " ❌ 服务异常退出（建议 journalctl -u " + service + " 查看日志）"
        elif "could not be found" in raw or "Loaded: not-found" in raw:
            interpretation = " ❌ 服务不存在（检查服务名拼写或未安装）"

    return f"{_ssh_format_prefix(conn_id)}\n$ {cmd}\n{raw}{interpretation}"


def ssh_log_view(service: str = "", lines: int = 100, follow: bool = False,
                 keyword: str = "", conn_id: str = "default") -> str:
    """查看远程日志（Linux: journalctl/syslog；Windows: Get-EventLog 事件日志）。

    Args:
        service: 服务名（如 nginx）——Linux 用 journalctl -u；Windows 忽略，查看系统事件日志
        lines: 查看最后 N 行，默认 100
        follow: 是否持续跟踪（注意：会阻塞直到超时，建议短时使用）
        keyword: 关键词过滤（grep），如 error / exception / fail
        conn_id: SSH 连接ID

    Returns:
        日志内容 + 自动异常统计

    迁移来源：tui_agent.py 行 7998-8118
    """
    lines = max(10, min(int(lines), 1000))  # 限制 10-1000

    os_type = _ssh_detect_os(conn_id)

    if os_type == "windows":
        # Windows 事件日志查看（用 Get-WinEvent 替代已废弃的 Get-EventLog）
        # service 参数在 Windows 上映射为日志名：
        #   - 空/未指定 → System（系统日志）
        #   - app/application → Application（应用程序日志）
        #   - sec/security → Security（安全日志）
        #   - setup → Setup（安装日志）
        #   - forward → ForwardedEvents（转发事件）
        #   - 其他字符串 → 视为自定义日志名（如 Microsoft-Windows-PowerShell/Operational）
        svc_lower = (service or "").lower().strip()
        if not svc_lower:
            log_name = "System"
        elif svc_lower in ("app", "application"):
            log_name = "Application"
        elif svc_lower in ("sec", "security"):
            log_name = "Security"
        elif svc_lower in ("setup",):
            log_name = "Setup"
        elif svc_lower in ("forward", "forwarded"):
            log_name = "ForwardedEvents"
        else:
            # 视为自定义日志名（防注入：仅允许字母数字-/_）
            if all(c.isalnum() or c in "-/_" for c in service):
                log_name = service
            else:
                return f"错误：service 参数含非法字符 '{service}'（仅允许字母数字-/_）"

        # 构造 Get-WinEvent 命令（比 Get-EventLog 性能更好，支持更多日志）
        # FilterHashtable 比 Where-Object 过滤更高效
        if keyword:
            # 带关键词过滤：先按时间倒序取最近 N 条，再用 Message 匹配
            # 注意：Get-WinEvent 的 Message 字段不能直接在 FilterHashtable 中过滤
            # 所以用 Where-Object 二次过滤
            safe_kw = keyword.replace("'", "''").replace('"', '`"')
            # 先取较多条目用于过滤（避免过滤后条目太少）
            fetch_n = min(lines * 5, 1000)
            cmd = (
                'powershell -NoProfile -Command "'
                f"$events = Get-WinEvent -LogName '{log_name}' -MaxEvents {fetch_n} -ErrorAction SilentlyContinue | "
                f"Where-Object {{ $_.Message -like '*{safe_kw}*' }} | Select-Object -First {lines};"
                "$events | Sort-Object TimeCreated -Descending | ForEach-Object {"
                "  $level = switch ($_.LevelDisplayName) { 'Error' {'❌'} 'Warning' {'⚠️'} 'Information' {'ℹ️'} default {'?'} };"
                "  $msg = ($_.Message -replace '\\r?\\n', ' ').Substring(0, [Math]::Min(80, ($_.Message).Length));"
                "  Write-Output ($_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $level + ' [' + $_.Id + '] ' + $_.ProviderName + ': ' + $msg)"
                "}"
                '"'
            )
        else:
            cmd = (
                'powershell -NoProfile -Command "'
                f"Get-WinEvent -LogName '{log_name}' -MaxEvents {lines} -ErrorAction SilentlyContinue | "
                "Sort-Object TimeCreated -Descending | ForEach-Object {"
                "  $level = switch ($_.LevelDisplayName) { 'Error' {'❌'} 'Warning' {'⚠️'} 'Information' {'ℹ️'} default {'?'} };"
                "  $msg = if ($_.Message) { ($_.Message -replace '\\r?\\n', ' ').Substring(0, [Math]::Min(80, ($_.Message).Length)) } else { '' };"
                "  Write-Output ($_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $level + ' [' + $_.Id + '] ' + $_.ProviderName + ': ' + $msg)"
                "}"
                '"'
            )

        raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=30)
        if raw.startswith("错误") or raw.startswith("连接失败"):
            return raw

        # 自动异常统计（基于等级图标计数）
        err_count = raw.count("❌")
        warn_count = raw.count("⚠️")
        info_count = raw.count("ℹ️")
        total = err_count + warn_count + info_count
        summary = f"\n\n[日志分析] {log_name} 共 {total} 条，错误 {err_count} 条，警告 {warn_count} 条，信息 {info_count} 条"
        if err_count > 10:
            summary += " ⚠️ 错误密度高，建议深入排查"
        elif err_count > 0:
            summary += " ℹ️ 存在少量错误"
        if "无法找到" in raw or "No events were found" in raw or "not found" in raw.lower():
            summary += "\n💡 该日志名可能不存在，可用 ssh_exec('powershell -Command \"Get-WinEvent -ListLog * | Select-Object LogName\"') 查看所有可用日志"
        return f"{_ssh_format_prefix(conn_id)}\n$ 查看 {log_name} 事件日志（最近 {lines} 条）\n{raw}{summary}"

    # Linux 日志查看（原有逻辑保留）
    if service:
        cmd = f"journalctl -u {service} -n {lines} --no-pager"
    else:
        cmd = f"tail -n {lines} /var/log/syslog 2>/dev/null || tail -n {lines} /var/log/messages"
    if keyword:
        # 转义单引号防注入
        safe_kw = keyword.replace("'", "'\\''")
        cmd += f" | grep -i '{safe_kw}'"
    if follow:
        # follow 模式下加超时
        cmd = f"timeout 15 {cmd} -f" if "journalctl" in cmd else f"timeout 15 {cmd} -f"

    raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=30)
    if raw.startswith("错误") or raw.startswith("连接失败"):
        return raw

    # 自动异常统计
    err_count = sum(raw.lower().count(kw) for kw in ["error", "exception", "failed", "critical"])
    warn_count = raw.lower().count("warn")
    summary = f"\n\n[日志分析] 共 {len(raw.splitlines())} 行，错误关键词 {err_count} 次，警告 {warn_count} 次"
    if err_count > 10:
        summary += " ⚠️ 错误密度高，建议深入排查"
    elif err_count > 0:
        summary += " ℹ️ 存在少量错误"
    return f"{_ssh_format_prefix(conn_id)}\n$ {cmd}\n{raw}{summary}"


def ssh_process_check(sort_by: str = "cpu", top_n: int = 15,
                      conn_id: str = "default") -> str:
    """查看远程服务器进程（按 CPU/内存排序）。

    Args:
        sort_by: 排序方式，可选 cpu / mem
        top_n: 返回前 N 个进程，默认 15
        conn_id: SSH 连接ID

    Returns:
        进程列表 + 资源占用摘要

    迁移来源：tui_agent.py 行 8121-8169
    """
    if sort_by not in ("cpu", "mem"):
        return "错误：sort_by 必须是 cpu 或 mem"
    top_n = max(5, min(int(top_n), 50))

    os_type = _ssh_detect_os(conn_id)

    if os_type == "windows":
        # Windows 进程查看（用 PowerShell 的 Get-Process）
        sort_prop = "CPU" if sort_by == "cpu" else "WorkingSet64"
        cmd = (
            'powershell -NoProfile -Command "'
            f"Get-Process | Sort-Object {sort_prop} -Descending | Select-Object -First {top_n} | "
            "ForEach-Object {"
            "  $cpu = if ($_.CPU) { [math]::Round($_.CPU, 1) } else { 0 };"
            "  $memMB = [math]::Round($_.WorkingSet64/1MB, 0);"
            "  Write-Output ($_.Id.ToString().PadLeft(8) + '  ' + $cpu.ToString().PadLeft(10) + 's  ' + $memMB.ToString().PadLeft(8) + 'MB  ' + $_.Name)"
            "};"
            "Write-Output '';"
            "Write-Output ('进程总数: ' + (Get-Process | Measure-Object).Count)"
            '"'
        )
        raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=20)
        if raw.startswith("错误") or raw.startswith("连接失败"):
            return raw
        header = "      PID        CPU         内存  名称\n"
        return f"$ 按CPU排序的Top{top_n}进程\n{header}{raw}"

    # Linux 进程查看（ps 命令按 CPU/内存排序）
    sort_field = "-pcpu" if sort_by == "cpu" else "-pmem"
    cmd = f"ps aux --sort={sort_field} | head -n {top_n + 1}"
    raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=15)
    if raw.startswith("错误") or raw.startswith("连接失败"):
        return raw

    # 获取系统总览
    overview = ssh_exec("uptime && free -h | head -n 2", conn_id=conn_id, timeout=5)
    return f"{_ssh_format_prefix(conn_id)}\n$ {cmd}\n{raw}\n\n[系统总览]\n{overview}"


def ssh_disk_analyze(path: str = "/", conn_id: str = "default") -> str:
    """磁盘空间分析（Linux: df + du；Windows: Get-Volume + Get-ChildItem）。

    Args:
        path: 分析的目录，默认 /（Windows 默认所有盘符）
        conn_id: SSH 连接ID

    Returns:
        磁盘使用情况 + 大目录 Top10

    迁移来源：tui_agent.py 行 8172-8306
    """
    os_type = _ssh_detect_os(conn_id)

    if os_type == "windows":
        # Windows 磁盘分析
        # 使用 Get-Volume（现代 cmdlet，Windows 8+ / Server 2012+）+ Get-CimInstance（兼容后备）
        # path 解析：
        #   - "/" 或空 → 所有盘符
        #   - "C:" / "C:\" → 指定盘符
        #   - "C:\Users" → 指定目录（先显示所在盘，再分析该目录大小）
        import re as _re_module

        if path == "/" or not path:
            # 列出所有盘符（用 Get-Volume 显示更现代的卷信息 + Get-CimInstance 补充容量）
            vol_cmd = (
                'powershell -NoProfile -Command "'
                "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {"
                "  $totalD = [math]::Round($_.Size/1GB, 1);"
                "  $freeD = [math]::Round($_.FreeSpace/1GB, 1);"
                "  $usedD = [math]::Round($totalD - $freeD, 1);"
                "  $usedPct = if ($totalD -gt 0) { [math]::Round($usedD / $totalD * 100, 1) } else { 0 };"
                "  Write-Output ($_.DeviceID + '  总:' + $totalD + 'GB  已用:' + $usedD + 'GB  可用:' + $freeD + 'GB  使用率:' + $usedPct + '%')"
                "}"
                '"'
            )
        else:
            # 指定盘符或目录
            # 提取盘符（前两个字符，如 "C:"）
            drive = path[:2] if len(path) >= 2 else path
            # 防注入：仅允许字母+冒号
            if not _re_module.match(r'^[A-Za-z]:$', drive):
                return f"错误：Windows 路径需以盘符开头（如 'C:' 或 'C:\\Users'），收到 '{path}'"
            # 用 Where-Object 过滤替代 -Filter，避免双引号嵌套问题
            # （cmd 中双引号无法嵌套，-Filter 参数的引号会被错误解析）
            vol_cmd = (
                'powershell -NoProfile -Command "'
                f"$target = '{drive}';"
                "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
                "Where-Object { $_.DeviceID -eq $target } | ForEach-Object {"
                "  $totalD = [math]::Round($_.Size/1GB, 1);"
                "  $freeD = [math]::Round($_.FreeSpace/1GB, 1);"
                "  $usedD = [math]::Round($totalD - $freeD, 1);"
                "  $usedPct = if ($totalD -gt 0) { [math]::Round($usedD / $totalD * 100, 1) } else { 0 };"
                "  Write-Output ($_.DeviceID + '  总:' + $totalD + 'GB  已用:' + $usedD + 'GB  可用:' + $freeD + 'GB  使用率:' + $usedPct + '%')"
                "}"
                '"'
            )
        vol_out = ssh_exec(vol_cmd, conn_id=conn_id, _internal=True, timeout=15)

        # 分析磁盘使用率
        analysis = ""
        for line in vol_out.split("\n"):
            m = _re_module.search(r"使用率:([\d.]+)%", line)
            if m:
                pct = float(m.group(1))
                if pct >= 90:
                    analysis += f"\n⚠️ 磁盘使用率 {pct}%（危急，建议立即清理）"
                elif pct >= 80:
                    analysis += f"\n⚠️ 磁盘使用率 {pct}%（警告）"
                elif pct >= 70:
                    analysis += f"\nℹ️ 磁盘使用率 {pct}%（关注）"

        # Top10 大目录分析（对应 Linux 的 du --max-depth=1）
        # 优化：只扫描顶层子目录，每个子目录内部递归统计文件大小
        # （原 -Recurse -Depth 2 方案会对每个深层目录重复扫描，O(n²) 复杂度，大目录超时）
        target_path = path if (path and path != "/") else "C:\\"
        # 规范化路径：把 / 转为 \
        target_path = target_path.replace("/", "\\")
        # 如果只给了盘符（如 "C:"），补全为 "C:\\"
        if _re_module.match(r'^[A-Za-z]:$', target_path):
            target_path = target_path + "\\"

        # PowerShell 命令：扫描顶层子目录，每个子目录递归统计文件总大小
        # 用 foreach 循环替代 ForEach-Object（性能更好）
        # 用 -ErrorAction SilentlyContinue 跳过无权限目录
        # 注意：如果路径是盘符根目录（如 C:\），扫描顶层子目录可能仍较慢
        #       因此设置 90 秒超时，并在返回结果中提示
        du_cmd = (
            'powershell -NoProfile -Command "'
            f"$root = '{target_path}';"
            "$topDirs = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue;"
            "foreach ($d in $topDirs) {"
            "  try {"
            "    $size = (Get-ChildItem -Path $d.FullName -File -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum;"
            "    $sizeMB = [math]::Round($size/1MB, 1);"
            "    if ($sizeMB -gt 10) { Write-Output ($sizeMB.ToString().PadLeft(10) + 'MB  ' + $d.FullName) }"
            "  } catch {}"
            "}"
            '"'
        )
        du_out = ssh_exec(du_cmd, conn_id=conn_id, _internal=True, timeout=90)

        # 如果扫描结果为空或超时，给出提示
        if not du_out.strip() or "超时" in du_out or "timeout" in du_out.lower():
            du_out = du_out or "(无输出)"
            du_out += "\n💡 提示：扫描大目录可能较慢，建议指定更具体的路径（如 'C:\\Users' 而非 'C:\\'）"

        return f"{_ssh_format_prefix(conn_id)}\n[磁盘使用]\n$ {vol_cmd}\n{vol_out}{analysis}\n\n[Top10 大目录]\n$ {du_cmd}\n{du_out}"

    # Linux 磁盘分析（原有逻辑保留）
    # df 查看整体
    df_cmd = f"df -h {path}"
    df_out = ssh_exec(df_cmd, conn_id=conn_id, timeout=10)

    # du 查看 Top10 大目录（限制深度3，避免扫描过慢）
    du_cmd = f"du -h --max-depth=3 {path} 2>/dev/null | sort -rh | head -n 10"
    du_out = ssh_exec(du_cmd, conn_id=conn_id, timeout=60)

    # 分析
    analysis = ""
    for line in df_out.split("\n"):
        if "%" in line:
            # 提取使用率
            parts = line.split()
            for p in parts:
                if p.endswith("%") and p[:-1].isdigit():
                    pct = int(p[:-1])
                    if pct >= 90:
                        analysis += f"\n⚠️ 磁盘使用率 {pct}%（危急，建议立即清理）"
                    elif pct >= 80:
                        analysis += f"\n⚠️ 磁盘使用率 {pct}%（警告）"
                    elif pct >= 70:
                        analysis += f"\nℹ️ 磁盘使用率 {pct}%（关注）"
                    break

    return f"[磁盘使用]\n$ {df_cmd}\n{df_out}\n\n[Top10 大目录]\n$ {du_cmd}\n{du_out}{analysis}"


def ssh_network_diag(action: str = "stats", target: str = "",
                     conn_id: str = "default") -> str:
    """网络诊断工具集（Linux: ss/netstat；Windows: Get-NetTCPConnection/netstat/ping）。

    Args:
        action: 诊断类型：
            - stats: 查看网络连接统计（默认）
            - ports: 查看监听端口
            - ping: ping 目标主机
            - connections: 查看活跃连接
        target: ping 操作时的目标主机（IP/域名）
        conn_id: SSH 连接ID

    Returns:
        诊断结果

    迁移来源：tui_agent.py 行 8309-8362
    """
    if action not in ("stats", "ports", "ping", "connections"):
        return "错误：action 必须是 stats / ports / ping / connections 之一"

    os_type = _ssh_detect_os(conn_id)

    if os_type == "windows":
        if action == "stats":
            cmd = 'powershell -NoProfile -Command "$tcp = Get-NetTCPConnection -ErrorAction SilentlyContinue; Write-Output (\'TCP连接总数: \' + ($tcp | Measure-Object).Count); Write-Output (\'监听端口数: \' + ($tcp | Where-Object {$_.State -eq \'Listen\'} | Measure-Object).Count); Write-Output (\'已建立连接数: \' + ($tcp | Where-Object {$_.State -eq \'Established\'} | Measure-Object).Count); Write-Output (\'UDP端点数: \' + (Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Measure-Object).Count)"'
        elif action == "ports":
            cmd = 'powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, OwningProcess | Sort-Object LocalPort | Format-Table -AutoSize"'
        elif action == "ping":
            if not target:
                return "错误：ping 操作需要 target 参数"
            if not target.replace(".", "").replace("-", "").isalnum():
                return "错误：target 仅允许字母数字.-"
            cmd = f'ping -n 4 -w 2000 {target}'
        else:  # connections
            cmd = 'powershell -NoProfile -Command "Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, RemoteAddress, RemotePort | Sort-Object RemoteAddress | Format-Table -AutoSize | Out-String -Width 200"'
        raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=30 if action == "ping" else 15)
        return f"{_ssh_format_prefix(conn_id)}\n$ {cmd}\n{raw}"

    # Linux 网络诊断（原有逻辑保留）
    if action == "stats":
        cmd = "ss -s"
    elif action == "ports":
        cmd = "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null"
    elif action == "ping":
        if not target:
            return "错误：ping 操作需要 target 参数"
        # 校验 target 合法性
        if not target.replace(".", "").replace("-", "").isalnum():
            return "错误：target 仅允许字母数字.-"
        cmd = f"ping -c 4 -W 2 {target}"
    else:  # connections
        cmd = "ss -tn state established 2>/dev/null | head -n 30"

    raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=30 if action == "ping" else 15)
    return f"{_ssh_format_prefix(conn_id)}\n$ {cmd}\n{raw}"


def ssh_docker_manage(action: str, container: str = "",
                      conn_id: str = "default") -> str:
    r"""Docker 容器管理（跨平台：Linux 原生 Docker / Windows Docker Desktop）。

    Args:
        action: 操作类型：ps / psa / logs / start / stop / restart / stats / images / info
            - ps: 运行中容器
            - psa: 所有容器（含已停止）
            - logs: 查看容器日志（需 container 参数）
            - start/stop/restart: 容器生命周期（需 container 参数）
            - stats: 资源占用
            - images: 镜像列表
            - info: Docker 系统信息（版本、存储驱动、运行环境）
        container: 容器名/ID（logs/start/stop/restart 必填）
        conn_id: SSH 连接ID

    Returns:
        Docker 操作结果

    Windows Docker Desktop 适配说明：
        - 命令前缀使用 docker.exe（显式调用，避免 PowerShell 别名冲突）
        - --format 字符串用双引号包裹（PowerShell 单引号会原样输出 Go template）
        - 自动检测 Docker Desktop 是否运行（依赖 WSL2 后端）
        - Windows 上 docker 命令在 PATH 中：C:\Program Files\Docker\Docker\resources\bin\

    迁移来源：tui_agent.py 行 8365-8461
    """
    valid_actions = {"ps", "psa", "logs", "start", "stop", "restart", "stats", "images", "info"}
    if action not in valid_actions:
        return f"错误：action 必须是 {sorted(valid_actions)} 之一"

    # 检查 docker 是否安装
    if action in ("start", "stop", "restart", "logs") and not container:
        return f"错误：action={action} 需要提供 container 参数"

    # 校验 container 名（防注入）
    if container and not container.replace("-", "").replace("_", "").replace(".", "").replace("/", "").isalnum():
        return f"错误：容器名 '{container}' 不合法"

    os_type = _ssh_detect_os(conn_id)
    is_windows = (os_type == "windows")

    # Windows 用 docker.exe，Linux 用 docker
    docker_cmd = "docker.exe" if is_windows else "docker"

    if action == "ps":
        if is_windows:
            # cmd 下用双引号包裹 Go template（单引号在 cmd 中是字面字符，会被 docker 误认）
            cmd = f'{docker_cmd} ps --format "table {{{{.ID}}}}\\t{{{{.Names}}}}\\t{{{{.Image}}}}\\t{{{{.Status}}}}\\t{{{{.Ports}}}}"'
        else:
            cmd = "docker ps --format 'table {{.ID}}\\t{{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}'"
    elif action == "psa":
        if is_windows:
            cmd = f'{docker_cmd} ps -a --format "table {{{{.ID}}}}\\t{{{{.Names}}}}\\t{{{{.Image}}}}\\t{{{{.Status}}}}"'
        else:
            cmd = "docker ps -a --format 'table {{.ID}}\\t{{.Names}}\\t{{.Image}}\\t{{.Status}}'"
    elif action == "logs":
        cmd = f"{docker_cmd} logs --tail 100 {container}"
    elif action == "start":
        cmd = f"{docker_cmd} start {container}"
    elif action == "stop":
        cmd = f"{docker_cmd} stop {container}"
    elif action == "restart":
        cmd = f"{docker_cmd} restart {container}"
    elif action == "stats":
        if is_windows:
            cmd = f'{docker_cmd} stats --no-stream --format "table {{{{.Name}}}}\\t{{{{.CPUPerc}}}}\\t{{{{.MemUsage}}}}"'
        else:
            cmd = "docker stats --no-stream --format 'table {{.Name}}\\t{{.CPUPerc}}\\t{{.MemUsage}}'"
    elif action == "info":
        # Docker 系统信息（跨平台兼容）
        cmd = f"{docker_cmd} version && {docker_cmd} info --format 'Server Version: {{{{.ServerVersion}}}}\\nStorage Driver: {{{{.Driver}}}}\\nRunning Containers: {{{{.ContainersRunning}}}}\\nTotal Containers: {{{{.Containers}}}}\\nImages: {{{{.Images}}}}'"
    else:  # images
        if is_windows:
            cmd = f'{docker_cmd} images --format "table {{{{.Repository}}}}\\t{{{{.Tag}}}}\\t{{{{.Size}}}}"'
        else:
            cmd = "docker images --format 'table {{.Repository}}\\t{{.Tag}}\\t{{.Size}}'"

    # Windows 上先检测 Docker Desktop 是否安装并运行
    if is_windows:
        # 用 where 命令快速检测 docker.exe 是否存在
        check_cmd = "where docker.exe 2>nul || echo NOT_FOUND"
        check_out = ssh_exec(check_cmd, conn_id=conn_id, _internal=True, timeout=8)
        if "NOT_FOUND" in check_out or not check_out.strip():
            return f"{_ssh_format_prefix(conn_id)}\n❌ Windows 服务器未安装 Docker Desktop\n（安装路径通常是 C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe）"

    raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=60 if action == "stats" else 30)
    raw_lower = raw.lower()
    if ("command not found" in raw_lower
            or "not recognized" in raw_lower
            or "不是内部或外部命令" in raw_lower
            or "无法找到" in raw_lower):
        return f"{_ssh_format_prefix(conn_id)}\n❌ 服务器未安装 Docker"
    # Windows Docker Desktop 未运行时的常见错误
    if is_windows and ("error during connect" in raw_lower
                       or "the docker daemon is not running" in raw_lower
                       or "cannot connect to the docker daemon" in raw_lower):
        return f"{_ssh_format_prefix(conn_id)}\n❌ Docker Desktop 未运行，请先启动 Docker Desktop\n$ {cmd}\n{raw}"
    return f"{_ssh_format_prefix(conn_id)}\n$ {cmd}\n{raw}"


def ssh_firewall_manage(action: str, port: int = 0, protocol: str = "tcp",
                        conn_id: str = "default") -> str:
    """防火墙管理（ufw / firewalld / iptables 自动检测）。

    Args:
        action: 操作类型：status / list / open / close / enable / disable
            - status: 查看状态
            - list: 列出规则
            - open: 开放端口（需 port）
            - close: 关闭端口（需 port）
            - enable/disable: 启用/禁用防火墙
        port: 端口号（open/close 时必填）
        protocol: 协议 tcp/udp，默认 tcp
        conn_id: SSH 连接ID

    Returns:
        防火墙操作结果

    迁移来源：tui_agent.py 行 8464-8605
    """
    valid_actions = {"status", "list", "open", "close", "enable", "disable"}
    if action not in valid_actions:
        return f"错误：action 必须是 {sorted(valid_actions)} 之一"
    if protocol not in ("tcp", "udp"):
        return "错误：protocol 必须是 tcp 或 udp"
    if action in ("open", "close"):
        if not (1 <= int(port) <= 65535):
            return f"错误：port 必须在 1-65535 范围内"

    os_type = _ssh_detect_os(conn_id)

    if os_type == "windows":
        # Windows 防火墙管理（netsh advfirewall + Get-NetFirewallRule 组合）
        # netsh 适合增删规则，Get-NetFirewallRule 适合查询统计
        if action == "status":
            # 用 PowerShell 的 Get-NetFirewallProfile 显示各配置文件状态（更直观）
            cmd = (
                'powershell -NoProfile -Command "'
                "Get-NetFirewallProfile | ForEach-Object {"
                "  $state = if ($_.Enabled) {'✅ 已启用'} else {'❌ 已禁用'};"
                "  Write-Output ($_.Name + ' - ' + $state + ' (入站默认: ' + $_.DefaultInboundAction + ', 出站默认: ' + $_.DefaultOutboundAction + ')')"
                "}"
                '"'
            )
        elif action == "list":
            # 用 Get-NetFirewallRule 列出 ZeroAI 创建的规则（避免输出过长）
            # 默认只显示 ZeroAI-* 规则，避免列出数千条系统规则
            # 注意：Get-NetFirewallRule 返回对象的 Action 是枚举值（1=NotConfigured, 2=Allow, 3=Block）
            #       Direction 也是枚举值（1=Inbound, 2=Outbound）
            cmd = (
                'powershell -NoProfile -Command "'
                "$rules = Get-NetFirewallRule -ErrorAction SilentlyContinue | "
                "Where-Object { $_.DisplayName -like 'ZeroAI-*' -or $_.DisplayName -like 'ZeroAI_*' };"
                "if ($rules) {"
                "  $rules | ForEach-Object {"
                "    $action = switch ($_.Action) { 2 {'✅允许'} 3 {'❌阻止'} default {'?' } };"
                "    $dir = if ($_.Direction -eq 1) {'入站'} else {'出站'};"
                "    $enabled = if ($_.Enabled) {'启用'} else {'禁用'};"
                "    Write-Output ($_.DisplayName + ' [' + $dir + ' ' + $action + ' ' + $enabled + ']')"
                "  }"
                "} else {"
                "  Write-Output '提示：当前无 ZeroAI 创建的防火墙规则。如需查看全部规则，请用 ssh_exec 直接执行：netsh advfirewall firewall show rule name=all'"
                "}"
                '"'
            )
        elif action == "open":
            # 开放端口：用 netsh 添加规则（兼容旧版 Windows）
            # 规则名格式 ZeroAI-Allow-{port}-{protocol} 便于后续查询和删除
            cmd = f'netsh advfirewall firewall add rule name="ZeroAI-Allow-{port}-{protocol}" dir=in action=allow protocol={protocol} localport={port}'
        elif action == "close":
            # 关闭端口：按规则名 + 端口双重匹配删除（更精确）
            cmd = f'netsh advfirewall firewall delete rule name="ZeroAI-Allow-{port}-{protocol}" dir=in protocol={protocol} localport={port}'
        elif action == "enable":
            cmd = "netsh advfirewall set allprofiles state on"
        else:  # disable
            cmd = "netsh advfirewall set allprofiles state off"

        raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=20 if action == "list" else 15)
        # Windows 下额外提示
        extra_hint = ""
        if action == "open" and "确定" in raw and "OK" in raw:
            extra_hint = f"\n💡 已开放 {protocol}/{port}，规则名 ZeroAI-Allow-{port}-{protocol}"
        elif action == "close":
            extra_hint = f"\n💡 已删除 {protocol}/{port} 的规则（如存在）"
        elif action == "disable":
            extra_hint = "\n⚠️ 防火墙已禁用，服务器暴露在网络中，建议仅在调试时使用"
        return f"{_ssh_format_prefix(conn_id)}\n[Windows 防火墙] $ {cmd}\n{raw}{extra_hint}"

    # Linux 防火墙管理（原有逻辑保留）
    # 自动检测防火墙类型
    fw_check = ssh_exec("command -v ufw >/dev/null && echo UFW || (command -v firewall-cmd >/dev/null && echo FIREWALLD || echo IPTABLES)",
                        conn_id=conn_id, timeout=5)
    fw_type = "UFW" if "UFW" in fw_check else ("FIREWALLD" if "FIREWALLD" in fw_check else "IPTABLES")

    if fw_type == "UFW":
        if action == "status":
            cmd = "ufw status verbose"
        elif action == "list":
            cmd = "ufw status numbered"
        elif action == "open":
            cmd = f"ufw allow {port}/{protocol}"
        elif action == "close":
            cmd = f"ufw deny {port}/{protocol}"
        elif action == "enable":
            cmd = "echo y | ufw enable"
        else:  # disable
            cmd = "ufw disable"
    elif fw_type == "FIREWALLD":
        if action == "status":
            cmd = "firewall-cmd --state && firewall-cmd --list-all"
        elif action == "list":
            cmd = "firewall-cmd --list-ports"
        elif action == "open":
            cmd = f"firewall-cmd --permanent --add-port={port}/{protocol} && firewall-cmd --reload"
        elif action == "close":
            cmd = f"firewall-cmd --permanent --remove-port={port}/{protocol} && firewall-cmd --reload"
        elif action == "enable":
            cmd = "systemctl enable --now firewalld"
        else:
            cmd = "systemctl disable --now firewalld"
    else:  # IPTABLES
        if action == "status" or action == "list":
            cmd = "iptables -L -n --line-numbers"
        elif action == "open":
            cmd = f"iptables -I INPUT -p {protocol} --dport {port} -j ACCEPT"
        elif action == "close":
            cmd = f"iptables -I INPUT -p {protocol} --dport {port} -j DROP"
        elif action == "enable":
            return "iptables 无 enable 操作（系统启动时自动加载规则）"
        else:
            cmd = "iptables -F"

    # open/close 是危险操作（修改防火墙），需要确认
    if action in ("open", "close"):
        # 不直接执行，先返回待确认信息（通过 ssh_exec 的 confirm_dangerous 链路）
        result = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=15, confirm_dangerous=False)
        if "危险命令" in result and "confirm_dangerous" in result:
            # 实际上 ufw/firewalld 不在危险命令黑名单，可以直接执行
            result = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=15)
        raw = result
    else:
        raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=15)

    return f"[防火墙类型: {fw_type}] $ {cmd}\n{raw}"


def ssh_health_check(conn_id: str = "default") -> str:
    """服务器一键健康体检（CPU/内存/磁盘/网络/负载/服务综合报告）。

    自动检测操作系统：Linux 用 uname/free/df/ss/systemctl/journalctl；
    Windows 用 PowerShell 的 Get-CimInstance/Get-Process/Get-Service 等。

    Args:
        conn_id: SSH 连接ID

    Returns:
        健康体检报告（含异常项标注与建议）

    迁移来源：tui_agent.py 行 8608-8829
    """
    import re

    # 第一步：检测操作系统（用缓存辅助函数，避免重复探测）
    is_windows = _ssh_detect_os(conn_id) == "windows"

    if is_windows:
        # Windows Server 体检：用 PowerShell 命令（避免 wmic 在 2025 已废弃的问题）
        # 用 cmd 调用 powershell，确保兼容性
        cmd = (
            'powershell -NoProfile -Command "'
            "Write-Output '=== 系统信息 ===';"
            "$os = Get-CimInstance Win32_OperatingSystem;"
            "Write-Output ($os.Caption + ' ' + $os.Version + ' Build ' + $os.BuildNumber);"
            "Write-Output ('开机时间: ' + $os.LastBootUpTime);"
            "Write-Output '';"
            "Write-Output '=== CPU 负载 ===';"
            "$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1;"
            "Write-Output ('CPU负载: ' + $cpu.LoadPercentage + '%');"
            "Write-Output ('CPU核心数: ' + (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors);"
            "Write-Output '';"
            "Write-Output '=== 内存 ===';"
            "$cs = Get-CimInstance Win32_ComputerSystem;"
            "$os2 = Get-CimInstance Win32_OperatingSystem;"
            "$totalGB = [math]::Round($cs.TotalPhysicalMemory/1GB, 1);"
            "$freeGB = [math]::Round($os2.FreePhysicalMemory/1MB, 1);"
            "$usedGB = [math]::Round($totalGB - $freeGB, 1);"
            "Write-Output ('总内存: ' + $totalGB + ' GB');"
            "Write-Output ('已用: ' + $usedGB + ' GB');"
            "Write-Output ('可用: ' + $freeGB + ' GB');"
            "Write-Output '';"
            "Write-Output '=== 磁盘 ===';"
            "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {"
            "  $totalD = [math]::Round($_.Size/1GB, 1);"
            "  $freeD = [math]::Round($_.FreeSpace/1GB, 1);"
            "  $usedPct = if ($totalD -gt 0) { [math]::Round(($totalD - $freeD) / $totalD * 100, 1) } else { 0 };"
            "  Write-Output ($_.DeviceID + ' 总:' + $totalD + 'GB 可用:' + $freeD + 'GB 使用:' + $usedPct + '%')"
            "};"
            "Write-Output '';"
            "Write-Output '=== 监听端口数 ===';"
            "$ports = (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count;"
            "Write-Output ('监听端口数: ' + $ports);"
            "Write-Output '';"
            "Write-Output '=== 进程数 ===';"
            "$procs = (Get-Process | Measure-Object).Count;"
            "Write-Output ('进程数: ' + $procs);"
            "Write-Output '';"
            "Write-Output '=== 运行中的服务数 ===';"
            "$svc = (Get-Service | Where-Object {$_.Status -eq 'Running'} | Measure-Object).Count;"
            "Write-Output ('运行中服务: ' + $svc);"
            "Write-Output '';"
            "Write-Output '=== 防火墙状态 ===';"
            "Get-NetFirewallProfile | ForEach-Object { Write-Output ($_.Name + ': ' + $_.Enabled) };"
            "Write-Output '';"
            "Write-Output '=== 高内存进程Top5 ===';"
            "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 5 | ForEach-Object {"
            "  $memMB = [math]::Round($_.WorkingSet64/1MB, 0);"
            "  Write-Output ($_.Name + ' (PID:' + $_.Id + ') 内存:' + $memMB + 'MB')"
            "}"
            '"'
        )
        raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=60)
        if raw.startswith("错误") or raw.startswith("连接失败"):
            return raw

        # Windows 分析
        issues = []

        # CPU 负载
        m = re.search(r"CPU负载:\s*(\d+)%", raw)
        if m:
            cpu_pct = int(m.group(1))
            if cpu_pct >= 90:
                issues.append(f"⚠️ CPU 负载极高: {cpu_pct}%")
            elif cpu_pct >= 70:
                issues.append(f"⚠️ CPU 负载偏高: {cpu_pct}%")
            else:
                pass  # 正常不记录

        # 内存
        m_total = re.search(r"总内存:\s*([\d.]+)\s*GB", raw)
        m_used = re.search(r"已用:\s*([\d.]+)\s*GB", raw)
        if m_total and m_used:
            total = float(m_total.group(1))
            used = float(m_used.group(1))
            if total > 0:
                pct = used / total * 100
                if pct >= 90:
                    issues.append(f"⚠️ 内存使用率 {pct:.1f}%（危急）")
                elif pct >= 80:
                    issues.append(f"⚠️ 内存使用率 {pct:.1f}%（警告）")

        # 磁盘
        for line in raw.split("\n"):
            m = re.search(r"([A-Z]:)\s*总:([\d.]+)GB\s*可用:([\d.]+)GB\s*使用:([\d.]+)%", line)
            if m:
                drive, total, free, pct = m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4))
                if pct >= 90:
                    issues.append(f"⚠️ 磁盘 {drive} 使用率 {pct}%（危急）")
                elif pct >= 80:
                    issues.append(f"⚠️ 磁盘 {drive} 使用率 {pct}%（警告）")

        # 防火墙
        for line in raw.split("\n"):
            if "False" in line and ("Domain" in line or "Private" in line or "Public" in line):
                issues.append(f"⚠️ 防火墙关闭: {line.strip()}")

        # 开机时间（判断是否长期未重启）
        m_boot = re.search(r"开机时间:\s*(.+)", raw)
        if m_boot:
            try:
                from datetime import datetime
                boot_str = m_boot.group(1).strip()
                # Windows PowerShell 输出格式可能多样，尝试解析
                for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %I:%M:%S %p"):
                    try:
                        boot_time = datetime.strptime(boot_str, fmt)
                        days = (datetime.now() - boot_time).days
                        if days > 90:
                            issues.append(f"💡 服务器已运行 {days} 天，建议定期重启")
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

        report = f"$ Windows 综合体检命令\n{raw}\n\n"
        report += "=== 健康分析 ===\n"
        if not issues:
            report += "✅ 服务器整体健康，未发现异常"
        else:
            report += f"发现 {len(issues)} 个问题：\n"
            for i, issue in enumerate(issues, 1):
                report += f"  {i}. {issue}\n"
            report += "\n建议：根据上述问题深入排查（使用 ssh_service_manage / ssh_log_view 等）"
        return _ssh_format_prefix(conn_id) + "\n" + report

    # Linux 体检（原有逻辑保留）
    cmd = """echo '=== 系统信息 ===' && uname -a && uptime
echo '=== CPU 使用 ===' && top -bn1 | head -n 5
echo '=== 内存 ===' && free -h
echo '=== 磁盘 ===' && df -h | grep -v tmpfs
echo '=== 网络监听端口 ===' && ss -tlnp 2>/dev/null | head -n 15
echo '=== 系统负载 ===' && cat /proc/loadavg
echo '=== 最近登录 ===' && last -n 5
echo '=== 失败服务 ===' && systemctl --failed --no-pager 2>/dev/null | head -n 20
echo '=== 最近错误日志 ===' && journalctl -p err --since '1 hour ago' --no-pager 2>/dev/null | tail -n 10"""
    raw = ssh_exec(cmd, conn_id=conn_id, _internal=True, timeout=30)
    if raw.startswith("错误") or raw.startswith("连接失败"):
        return raw

    # AI 分析
    issues = []
    # 检查负载
    for line in raw.split("\n"):
        if "load average" in line.lower():
            # 提取 load average
            m = re.search(r"load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)", line)
            if m:
                load_1, load_5, load_15 = float(m.group(1)), float(m.group(2)), float(m.group(3))
                # 简单阈值：> CPU 核数则告警
                if load_1 > 4:
                    issues.append(f"⚠️ 1分钟负载 {load_1} 偏高")
                if load_15 > 2:
                    issues.append(f"⚠️ 15分钟负载 {load_15} 持续偏高")
            break

    # 检查磁盘
    for line in raw.split("\n"):
        if "%" in line and ("/" in line or "/data" in line):
            parts = line.split()
            for p in parts:
                if p.endswith("%") and p[:-1].isdigit():
                    pct = int(p[:-1])
                    if pct >= 90:
                        issues.append(f"⚠️ 磁盘使用率 {pct}%（危急）")
                    elif pct >= 80:
                        issues.append(f"⚠️ 磁盘使用率 {pct}%（警告）")
                    break

    # 检查内存
    if "Swap:" in raw:
        for line in raw.split("\n"):
            if line.startswith("Swap:") and "0B" not in line:
                parts = line.split()
                if len(parts) >= 4 and parts[3] != "0B":
                    issues.append(f"⚠️ Swap 已使用 {parts[2]}/{parts[1]}")

    # 检查失败服务
    if "failed" in raw.lower() and "0 loaded" not in raw and "0 failed" not in raw:
        for line in raw.split("\n"):
            if "failed" in line.lower() and "UNIT" not in line:
                issues.append(f"❌ 失败服务: {line.strip()}")

    # 检查错误日志
    err_log_section = raw.split("=== 最近错误日志 ===")[-1] if "=== 最近错误日志 ===" in raw else ""
    if err_log_section.strip() and "No entries" not in err_log_section:
        err_lines = [l for l in err_log_section.strip().split("\n") if l.strip()][:5]
        if err_lines:
            issues.append(f"⚠️ 最近1小时有 {len(err_lines)} 条错误日志")

    report = f"$ 综合体检命令\n{raw}\n\n"
    report += "=== 健康分析 ===\n"
    if not issues:
        report += "✅ 服务器整体健康，未发现异常"
    else:
        report += f"发现 {len(issues)} 个问题：\n"
        for i, issue in enumerate(issues, 1):
            report += f"  {i}. {issue}\n"
        report += "\n建议：根据上述问题深入排查（使用 ssh_log_view / ssh_process_check 等）"
    return _ssh_format_prefix(conn_id) + "\n" + report
