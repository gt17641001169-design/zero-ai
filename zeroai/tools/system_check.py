"""系统检查工具

迁移来源：tui_agent.py 行 2142-2724, 3163-3212, 3346-3387

提供以下纯函数：
- local_port_check：本地端口/网络检查（跨平台）
- local_process_check：本地进程查看（跨平台）
- local_disk_check：本地磁盘空间分析（跨平台）
- local_service_check：本地服务管理（跨平台）
- local_firewall_check：本地防火墙检查/管理（跨平台）
- local_user_check：本地用户/登录管理（跨平台）
- local_monitor：本地综合监控告警
- system_info：系统信息
- process_list：进程列表
- check_port：端口占用检查

依赖：
- command_exec.run_command：执行 shell 命令
- command_exec._is_windows_local：判断 Windows 本地
- zeroai.core.constants：PERMISSION_LEVEL
- 标准库：os, platform, subprocess, socket, re
"""
import os
import platform
import subprocess
import socket
import re

from zeroai.core.constants import PERMISSION_LEVEL
from .command_exec import run_command, _is_windows_local


def local_port_check(action: str = "list", port: int = 0,
                     protocol: str = "tcp", target: str = "") -> str:
    r"""本地端口/网络检查工具（跨平台：Windows/Linux 自动适配）。

    Args:
        action: 操作类型：
            - list: 列出所有监听端口（默认）
            - check: 检查指定端口是否被占用（需 port 参数）
            - ping: ping 目标主机（需 target 参数）
            - connections: 查看活跃 TCP 连接
        port: 端口号（action=check 时必填）
        protocol: 协议（tcp/udp），默认 tcp
        target: 目标主机/IP（action=ping 时必填）

    Returns:
        端口/网络检查结果

    迁移来源：tui_agent.py 行 2142-2213
    """
    if action == "list":
        if _is_windows_local():
            cmd = "netstat -ano | findstr LISTENING"
        else:
            cmd = "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null"
        return run_command(cmd)

    elif action == "check":
        if not port:
            return "错误：action=check 需要 port 参数"
        # 跨平台端口占用检查
        try:
            sock_type = socket.SOCK_STREAM if protocol.lower() == "tcp" else socket.SOCK_DGRAM
            s = socket.socket(socket.AF_INET, sock_type)
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", port))
            s.close()
            if result == 0:
                # 端口被占用，查询占用进程
                if _is_windows_local():
                    proc_cmd = f"netstat -ano | findstr :{port}"
                    proc_out = run_command(proc_cmd, skip_translate=True)
                    return f"⚠️ 端口 {port}/{protocol} 已被占用\n\n{proc_out}"
                else:
                    proc_cmd = f"lsof -i :{port} 2>/dev/null || ss -tlnp | grep :{port}"
                    proc_out = run_command(proc_cmd, skip_translate=True)
                    return f"⚠️ 端口 {port}/{protocol} 已被占用\n\n{proc_out}"
            else:
                return f"✅ 端口 {port}/{protocol} 未被占用（可使用）"
        except Exception as e:
            return f"错误：检查端口失败 - {e}"

    elif action == "ping":
        if not target:
            return "错误：action=ping 需要 target 参数"
        # 防注入：仅允许字母数字点破折号
        if not all(c.isalnum() or c in ".-" for c in target):
            return f"错误：target 含非法字符 '{target}'"
        if _is_windows_local():
            cmd = f"ping -n 4 {target}"
        else:
            cmd = f"ping -c 4 {target}"
        return run_command(cmd)

    elif action == "connections":
        if _is_windows_local():
            cmd = "netstat -ano | findstr ESTABLISHED"
        else:
            cmd = "ss -tn state established 2>/dev/null || netstat -tn | grep ESTABLISHED"
        return run_command(cmd)

    else:
        return f"错误：action 必须是 list/check/ping/connections 之一"


def local_process_check(action: str = "top", name: str = "",
                        pid: int = 0, top_n: int = 10) -> str:
    """本地进程查看工具（跨平台：Windows/Linux 自动适配）。

    Args:
        action: 操作类型：
            - top: 按 CPU 占用排序显示前 N 个进程（默认）
            - memory: 按内存占用排序显示前 N 个进程
            - find: 按名称查找进程（需 name 参数）
            - kill: 结束指定进程（需 pid 或 name 参数）
        name: 进程名（action=find/kill 时使用）
        pid: 进程 ID（action=kill 时使用，优先于 name）
        top_n: 返回前 N 个进程（默认 10）

    Returns:
        进程信息

    迁移来源：tui_agent.py 行 2216-2289
    """
    if action == "top":
        if _is_windows_local():
            # PowerShell 按 CPU 排序（内部用单引号避免与外层双引号冲突）
            cmd = (
                'powershell -NoProfile -Command "'
                f"Get-Process | Sort-Object CPU -Descending | Select-Object -First {top_n} "
                "Id, ProcessName, CPU, @{N='Mem(MB)';E={[int]($_.WorkingSet/1MB)}} | Format-Table -AutoSize"
                '"'
            )
        else:
            cmd = f"ps aux --sort=-%cpu | head -n {top_n + 1}"
        return run_command(cmd, skip_translate=True)

    elif action == "memory":
        if _is_windows_local():
            cmd = (
                'powershell -NoProfile -Command "'
                f"Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First {top_n} "
                "Id, ProcessName, CPU, @{N='Mem(MB)';E={[int]($_.WorkingSet/1MB)}} | Format-Table -AutoSize"
                '"'
            )
        else:
            cmd = f"ps aux --sort=-%mem | head -n {top_n + 1}"
        return run_command(cmd, skip_translate=True)

    elif action == "find":
        if not name:
            return "错误：action=find 需要 name 参数"
        # 防注入：仅允许字母数字点下划线
        if not all(c.isalnum() or c in "._-" for c in name):
            return f"错误：name 含非法字符 '{name}'"
        if _is_windows_local():
            cmd = f'tasklist | findstr /I "{name}"'
        else:
            cmd = f"ps aux | grep -i {name} | grep -v grep"
        return run_command(cmd)

    elif action == "kill":
        if pid:
            if _is_windows_local():
                cmd = f"taskkill /PID {pid} /F"
            else:
                cmd = f"kill -9 {pid}"
            return run_command(cmd)
        elif name:
            if not all(c.isalnum() or c in "._-" for c in name):
                return f"错误：name 含非法字符 '{name}'"
            if _is_windows_local():
                cmd = f'taskkill /IM "{name}" /F'
            else:
                cmd = f"pkill -f {name}"
            return run_command(cmd)
        else:
            return "错误：action=kill 需要 pid 或 name 参数"

    else:
        return f"错误：action 必须是 top/memory/find/kill 之一"


def local_disk_check(action: str = "list", path: str = "") -> str:
    """本地磁盘空间分析工具（跨平台：Windows/Linux 自动适配）。

    Args:
        action: 操作类型：
            - list: 列出所有磁盘及使用率（默认）
            - top: 显示指定目录下 Top10 大目录/文件
        path: action=top 时指定分析目录（Windows: 'C:' 或 'C:\\Users'；Linux: '/var'），默认根目录

    Returns:
        磁盘使用情况

    迁移来源：tui_agent.py 行 2292-2336
    """
    if action == "list":
        if _is_windows_local():
            cmd = ('powershell -NoProfile -Command "Get-CimInstance Win32_LogicalDisk -Filter \'DriveType=3\' | '
                   "ForEach-Object { $t=[math]::Round($_.Size/1GB,1); $f=[math]::Round($_.FreeSpace/1GB,1); "
                   "$u=[math]::Round($t-$f,1); $p=if($t-gt 0){[math]::Round($u/$t*100,1)}else{0}; "
                   "Write-Output ($_.DeviceID + ' 总:' + $t + 'GB 已用:' + $u + 'GB 可用:' + $f + 'GB 使用率:' + $p + '%') }\"")
        else:
            cmd = "df -h"
        return run_command(cmd)

    elif action == "top":
        if _is_windows_local():
            target = path if path else "C:\\"
            target = target.replace("/", "\\")
            # 扫描顶层子目录大小
            cmd = (
                'powershell -NoProfile -Command "'
                f"$root = '{target}';"
                "$dirs = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue;"
                "foreach ($d in $dirs) { try {"
                "  $size = (Get-ChildItem -Path $d.FullName -File -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum;"
                "  $mb = [math]::Round($size/1MB, 1);"
                "  if ($mb -gt 10) { Write-Output ($mb.ToString().PadLeft(10) + 'MB  ' + $d.FullName) }"
                "} catch {} }\""
            )
            return run_command(cmd)
        else:
            target = path if path else "/"
            cmd = f"du -h --max-depth=1 {target} 2>/dev/null | sort -rh | head -n 10"
            return run_command(cmd)

    else:
        return f"错误：action 必须是 list/top 之一"


def local_service_check(action: str = "list", service: str = "") -> str:
    """本地服务管理工具（跨平台：Windows/Linux 自动适配）。

    Args:
        action: 操作类型：
            - list: 列出所有运行中的服务（默认）
            - status: 查看指定服务状态（需 service 参数）
            - start: 启动服务（需管理员权限）
            - stop: 停止服务（需管理员权限）
            - restart: 重启服务（需管理员权限）
        service: 服务名（action=status/start/stop/restart 时必填）

    Returns:
        服务信息

    迁移来源：tui_agent.py 行 2339-2385
    """
    if action == "list":
        if _is_windows_local():
            cmd = 'powershell -NoProfile -Command "Get-Service | Where-Object {$_.Status -eq \'Running\'} | Select-Object Status, Name, DisplayName | Format-Table -AutoSize"'
        else:
            cmd = "systemctl list-units --type=service --state=running 2>/dev/null | head -n 30"
        return run_command(cmd)

    elif action in ("status", "start", "stop", "restart"):
        if not service:
            return f"错误：action={action} 需要 service 参数"
        # 防注入：仅允许字母数字点下划线破折号
        if not all(c.isalnum() or c in "._-" for c in service):
            return f"错误：service 含非法字符 '{service}'"

        if _is_windows_local():
            if action == "status":
                cmd = f'powershell -NoProfile -Command "Get-Service -Name {service} -ErrorAction SilentlyContinue | Select-Object Status, Name, DisplayName | Format-Table -AutoSize"'
            elif action == "start":
                cmd = f'powershell -NoProfile -Command "Start-Service -Name {service}"'
            elif action == "stop":
                cmd = f'powershell -NoProfile -Command "Stop-Service -Name {service} -Force"'
            elif action == "restart":
                cmd = f'powershell -NoProfile -Command "Restart-Service -Name {service} -Force"'
        else:
            if action == "status":
                cmd = f"systemctl status {service}"
            else:
                cmd = f"sudo systemctl {action} {service}"
        return run_command(cmd)

    else:
        return f"错误：action 必须是 list/status/start/stop/restart 之一"


def local_firewall_check(action: str = "list", port: int = 0,
                         protocol: str = "tcp", direction: str = "in",
                         rule_name: str = "") -> str:
    r"""本地防火墙检查/管理工具（跨平台：Windows/Linux 自动适配）。

    Args:
        action: 操作类型：
            - list: 列出所有防火墙规则（默认）
            - status: 查看防火墙整体状态
            - check: 检查指定端口是否放行（需 port 参数）
            - open: 放行指定端口（需 port 参数，可能需管理员权限）
            - close: 关闭指定端口（需 port 参数，可能需管理员权限）
        port: 端口号（action=check/open/close 时必填）
        protocol: 协议（tcp/udp），默认 tcp
        direction: 方向（in/out），默认 in（入站）
        rule_name: 规则名（action=open/close 时可选，默认自动生成）

    Returns:
        防火墙信息

    迁移来源：tui_agent.py 行 2388-2463
    """
    # 防注入：rule_name 仅允许字母数字空格下划线破折号
    if rule_name and not all(c.isalnum() or c in " _-" for c in rule_name):
        return f"错误：rule_name 含非法字符 '{rule_name}'"

    if action == "list":
        if _is_windows_local():
            cmd = 'powershell -NoProfile -Command "Get-NetFirewallRule | Where-Object {$_.Enabled -eq \'True\'} | Select-Object DisplayName, Direction, Action, Profile -First 30 | Format-Table -AutoSize"'
        else:
            # Linux: 优先 ufw，其次 firewalld，最后 iptables
            cmd = "ufw status 2>/dev/null || firewall-cmd --list-all 2>/dev/null || iptables -L -n 2>/dev/null | head -n 30"
        return run_command(cmd, skip_translate=True)

    elif action == "status":
        if _is_windows_local():
            cmd = 'powershell -NoProfile -Command "Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction | Format-Table -AutoSize"'
        else:
            cmd = "ufw status verbose 2>/dev/null || systemctl is-active firewalld 2>/dev/null || iptables -L -n 2>/dev/null | head -n 10"
        return run_command(cmd, skip_translate=True)

    elif action == "check":
        if not port:
            return "错误：action=check 需要 port 参数"
        if _is_windows_local():
            # 查找放行该端口的规则
            cmd = f'powershell -NoProfile -Command "Get-NetFirewallRule -Enabled True | Where-Object {{($_.Direction -eq \'{direction.capitalize()}\') -and ($_.Action -eq \'Allow\')}} | Get-NetFirewallPortFilter | Where-Object {{($_.LocalPort -eq \'{port}\') -and ($_.Protocol -eq \'{protocol.upper()}\')}} | Format-List"'
            return run_command(cmd, skip_translate=True)
        else:
            cmd = f"ufw status | grep ':?{port} ' 2>/dev/null || iptables -L -n | grep ':{port} ' 2>/dev/null"
            result = run_command(cmd, skip_translate=True)
            if "无输出" in result or not result.strip():
                return f"⚠️ 端口 {port}/{protocol} 未在防火墙规则中找到放行记录（可能被阻止）"
            return f"✅ 端口 {port}/{protocol} 已放行\n\n{result}"

    elif action in ("open", "close"):
        if not port:
            return "错误：action=open/close 需要 port 参数"
        if not rule_name:
            rule_name = f"ZeroAI_{protocol}_{port}_{direction}"
        if _is_windows_local():
            action_ps = "Allow" if action == "open" else "Block"
            cmd = (
                f'powershell -NoProfile -Command "'
                f"New-NetFirewallRule -DisplayName '{rule_name}' "
                f"-Direction {direction.capitalize()} -Action {action_ps} "
                f"-Protocol {protocol.upper()} -LocalPort {port}"
                f'"'
            )
        else:
            if action == "open":
                cmd = f"ufw allow {port}/{protocol} 2>/dev/null || firewall-cmd --add-port={port}/{protocol} --permanent 2>/dev/null && firewall-cmd --reload 2>/dev/null || iptables -I INPUT -p {protocol} --dport {port} -j ACCEPT"
            else:
                cmd = f"ufw deny {port}/{protocol} 2>/dev/null || firewall-cmd --remove-port={port}/{protocol} --permanent 2>/dev/null && firewall-cmd --reload 2>/dev/null || iptables -D INPUT -p {protocol} --dport {port} -j ACCEPT"
        return run_command(cmd, skip_translate=True)

    else:
        return f"错误：action 必须是 list/status/check/open/close 之一"


def local_user_check(action: str = "list", username: str = "",
                     detail: bool = False) -> str:
    r"""本地用户/登录管理工具（跨平台：Windows/Linux 自动适配）。

    Args:
        action: 操作类型：
            - list: 列出所有本地用户（默认）
            - current: 查看当前登录用户
            - info: 查看指定用户详情（需 username 参数）
            - groups: 查看指定用户所属组（需 username 参数）
            - sessions: 查看当前登录会话
        username: 用户名（action=info/groups 时必填）
        detail: 是否显示详细信息（action=list 时有效）

    Returns:
        用户信息

    迁移来源：tui_agent.py 行 2466-2530
    """
    # 防注入：username 仅允许字母数字点下划线破折号
    if username and not all(c.isalnum() or c in "._-" for c in username):
        return f"错误：username 含非法字符 '{username}'"

    if action == "list":
        if _is_windows_local():
            if detail:
                cmd = 'powershell -NoProfile -Command "Get-LocalUser | Select-Object Name, Enabled, LastLogon, Description | Format-Table -AutoSize"'
            else:
                cmd = 'powershell -NoProfile -Command "Get-LocalUser | Select-Object Name, Enabled | Format-Table -AutoSize"'
        else:
            cmd = "cat /etc/passwd | cut -d: -f1,3,7 | head -n 50"
        return run_command(cmd, skip_translate=True)

    elif action == "current":
        if _is_windows_local():
            cmd = 'powershell -NoProfile -Command "whoami; Get-LocalUser | Where-Object {$_.Name -eq $env:USERNAME} | Select-Object Name, Enabled, LastLogon"'
        else:
            cmd = "whoami && id"
        return run_command(cmd, skip_translate=True)

    elif action == "info":
        if not username:
            return "错误：action=info 需要 username 参数"
        if _is_windows_local():
            cmd = f'powershell -NoProfile -Command "Get-LocalUser -Name {username} | Select-Object Name, Enabled, FullName, Description, LastLogon, PasswordLastSet | Format-List"'
        else:
            cmd = f"id {username} 2>/dev/null && grep '^{username}:' /etc/passwd"
        return run_command(cmd, skip_translate=True)

    elif action == "groups":
        if not username:
            return "错误：action=groups 需要 username 参数"
        if _is_windows_local():
            cmd = f'powershell -NoProfile -Command "Get-LocalGroup | Where-Object {{(Get-LocalGroupMember -Group $_.Name -ErrorAction SilentlyContinue).Name -contains \'{username}\'}} | Select-Object Name, Description | Format-Table -AutoSize"'
        else:
            cmd = f"groups {username} 2>/dev/null"
        return run_command(cmd, skip_translate=True)

    elif action == "sessions":
        if _is_windows_local():
            cmd = 'powershell -NoProfile -Command "query user 2>$null; Get-CimInstance Win32_LogonSession | Select-Object LogonId, LogonType, StartTime -First 10 | Format-Table -AutoSize"'
        else:
            cmd = "who -a 2>/dev/null | head -n 20"
        return run_command(cmd, skip_translate=True)

    else:
        return f"错误：action 必须是 list/current/info/groups/sessions 之一"


def local_monitor(threshold_cpu: int = 80, threshold_disk: int = 90,
                  threshold_memory: int = 85, check_ports: str = "") -> str:
    r"""本地综合监控告警：一次性检查 CPU/内存/磁盘/端口/防火墙，返回结构化告警报告。

    跨平台自动适配 Windows/Linux。基于本地运维工具组合调用，输出标准化告警。

    Args:
        threshold_cpu: CPU 使用率告警阈值（默认 80%）
        threshold_disk: 磁盘使用率告警阈值（默认 90%）
        threshold_memory: 内存使用率告警阈值（默认 85%）
        check_ports: 需要检查的关键端口（逗号分隔，如 "22,80,443,3306,8080"）
                     为空则只列出当前监听端口，不针对性检查

    Returns:
        结构化告警报告：
        [监控概览] 总体健康状态
        [告警项] ⚠️ 警告 / 🚨 危急
        [正常项] ✅ 正常
        [建议] 💡 优化建议

    迁移来源：tui_agent.py 行 2533-2722
    """
    import time as _time

    report_lines = ["=" * 60]
    report_lines.append(f"📊 本地监控告警报告  {_time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("=" * 60)

    warnings = []   # ⚠️ 警告
    criticals = []  # 🚨 危急
    normals = []    # ✅ 正常
    suggestions = []  # 💡 建议

    # ===== 1. CPU 检查 =====
    try:
        if _is_windows_local():
            cmd = 'powershell -NoProfile -Command "(Get-CimInstance Win32_Processor).LoadPercentage"'
        else:
            cmd = "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'"
        cpu_out = run_command(cmd, skip_translate=True)
        # 解析 CPU 使用率
        cpu_pct = -1
        for line in cpu_out.split("\n"):
            line = line.strip()
            if line and any(c.isdigit() for c in line):
                # 提取第一个数字
                m = re.search(r"(\d+)", line)
                if m:
                    cpu_pct = int(m.group(1))
                    break
        if cpu_pct >= 0:
            if cpu_pct >= threshold_cpu + 10:
                criticals.append(f"CPU 使用率 {cpu_pct}%（危急，阈值 {threshold_cpu}%）")
                suggestions.append("CPU 占用过高，建议用 local_process_check(action='top') 查看高 CPU 进程")
            elif cpu_pct >= threshold_cpu:
                warnings.append(f"CPU 使用率 {cpu_pct}%（警告，阈值 {threshold_cpu}%）")
            else:
                normals.append(f"CPU 使用率 {cpu_pct}%（正常）")
        else:
            warnings.append("CPU 使用率获取失败")
    except Exception as e:
        warnings.append(f"CPU 检查异常: {e}")

    # ===== 2. 内存检查 =====
    try:
        if _is_windows_local():
            cmd = 'powershell -NoProfile -Command "$os = Get-CimInstance Win32_OperatingSystem; [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / $os.TotalVisibleMemorySize * 100, 1)"'
        else:
            cmd = "free | grep Mem | awk '{printf \"%.1f\", $3/$2*100}'"
        mem_out = run_command(cmd, skip_translate=True).strip()
        m = re.search(r"(\d+(?:\.\d+)?)", mem_out)
        if m:
            mem_pct = float(m.group(1))
            if mem_pct >= threshold_memory + 10:
                criticals.append(f"内存使用率 {mem_pct}%（危急，阈值 {threshold_memory}%）")
                suggestions.append("内存占用过高，建议用 local_process_check(action='memory') 查看高内存进程")
            elif mem_pct >= threshold_memory:
                warnings.append(f"内存使用率 {mem_pct}%（警告，阈值 {threshold_memory}%）")
            else:
                normals.append(f"内存使用率 {mem_pct}%（正常）")
        else:
            warnings.append("内存使用率获取失败")
    except Exception as e:
        warnings.append(f"内存检查异常: {e}")

    # ===== 3. 磁盘检查 =====
    try:
        disk_out = local_disk_check(action="list")
        # 匹配使用率百分比
        pcts = re.findall(r"(\d+)%", disk_out)
        disk_high = False
        for pct_str in pcts:
            pct = int(pct_str)
            if pct >= threshold_disk + 5:
                criticals.append(f"磁盘使用率 {pct}%（危急，阈值 {threshold_disk}%）")
                disk_high = True
            elif pct >= threshold_disk:
                warnings.append(f"磁盘使用率 {pct}%（警告，阈值 {threshold_disk}%）")
                disk_high = True
        if not disk_high:
            normals.append(f"所有磁盘使用率低于 {threshold_disk}%（正常）")
        if disk_high:
            suggestions.append("磁盘空间不足，建议用 local_disk_check(action='top') 分析大目录")
    except Exception as e:
        warnings.append(f"磁盘检查异常: {e}")

    # ===== 4. 关键端口检查 =====
    if check_ports:
        for port_str in check_ports.split(","):
            port_str = port_str.strip()
            if not port_str.isdigit():
                continue
            port = int(port_str)
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                result = s.connect_ex(("127.0.0.1", port))
                s.close()
                if result == 0:
                    normals.append(f"端口 {port} 已监听（正常）")
                else:
                    # 判断是否为常见关键端口
                    critical_ports = {22: "SSH", 80: "HTTP", 443: "HTTPS", 3306: "MySQL", 5432: "PostgreSQL", 6379: "Redis"}
                    service_name = critical_ports.get(port, "")
                    if service_name:
                        criticals.append(f"关键端口 {port} ({service_name}) 未监听（危急）")
                        suggestions.append(f"端口 {port} ({service_name}) 未监听，建议用 local_service_check(action='status', service='{service_name.lower()}') 检查服务状态")
                    else:
                        warnings.append(f"端口 {port} 未监听")
            except Exception as e:
                warnings.append(f"端口 {port} 检查异常: {e}")

    # ===== 5. 防火墙状态检查 =====
    try:
        fw_out = local_firewall_check(action="status")
        fw_lower = fw_out.lower()
        if _is_windows_local():
            if "true" in fw_lower and "enabled" in fw_lower:
                normals.append("防火墙已启用（正常）")
            else:
                criticals.append("防火墙未启用（危急，建议立即启用）")
                suggestions.append("防火墙关闭会暴露所有端口，建议立即用 local_firewall_check(action='status') 检查并启用")
        else:
            if "active" in fw_lower or "active: active" in fw_lower:
                normals.append("防火墙已启用（正常）")
            else:
                warnings.append("防火墙可能未启用")
    except Exception as e:
        warnings.append(f"防火墙检查异常: {e}")

    # ===== 汇总报告 =====
    total_issues = len(warnings) + len(criticals)
    if not criticals and not warnings:
        status_emoji = "✅"
        status_text = "健康"
    elif criticals:
        status_emoji = "🚨"
        status_text = f"危急（{len(criticals)} 项危急，{len(warnings)} 项警告）"
    else:
        status_emoji = "⚠️"
        status_text = f"警告（{len(warnings)} 项警告）"

    report_lines.append(f"\n[{status_emoji} 监控概览] 总体状态：{status_text}")
    report_lines.append(f"  检查项：CPU/内存/磁盘/端口/防火墙")
    report_lines.append(f"  阈值：CPU≥{threshold_cpu}%  内存≥{threshold_memory}%  磁盘≥{threshold_disk}%")

    if criticals:
        report_lines.append(f"\n[🚨 危急项]")
        for item in criticals:
            report_lines.append(f"  🚨 {item}")

    if warnings:
        report_lines.append(f"\n[⚠️ 警告项]")
        for item in warnings:
            report_lines.append(f"  ⚠️ {item}")

    if normals:
        report_lines.append(f"\n[✅ 正常项]")
        for item in normals:
            report_lines.append(f"  ✅ {item}")

    if suggestions:
        report_lines.append(f"\n[💡 优化建议]")
        for item in suggestions:
            report_lines.append(f"  💡 {item}")

    report_lines.append("\n" + "=" * 60)
    return "\n".join(report_lines)


def system_info() -> str:
    """获取系统信息（CPU/内存/磁盘）

    迁移来源：tui_agent.py 行 3163-3185
    """
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.getcwd())
        return (
            f"系统：{platform.system()} {platform.release()}\n"
            f"架构：{platform.machine()}\n"
            f"Python：{platform.python_version()}\n"
            f"CPU 使用率：{cpu}%\n"
            f"内存：{mem.percent}%（{mem.used//1024//1024}MB / {mem.total//1024//1024}MB）\n"
            f"磁盘：{disk.percent}%（{disk.used//1024//1024//1024}GB / {disk.total//1024//1024//1024}GB）"
        )
    except ImportError:
        return (
            f"系统：{platform.system()} {platform.release()}\n"
            f"架构：{platform.machine()}\n"
            f"Python：{platform.python_version()}\n"
            f"（安装 psutil 可查看 CPU/内存/磁盘详情：pip install psutil）"
        )
    except Exception as e:
        return f"错误：{e}"


def process_list(name_filter: str = "") -> str:
    """全权限模式：显示所有进程，无 30 条截断

    迁移来源：tui_agent.py 行 3188-3210
    """
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                          capture_output=True, text=True, timeout=10)
        lines = r.stdout.strip().splitlines()
        results = []
        # 全权限：限制 200；受限：30
        max_results = 200 if PERMISSION_LEVEL == "full" else 30
        for line in lines:
            parts = line.replace('"', '').split(",")
            if len(parts) >= 2:
                pname = parts[0]
                pid = parts[1]
                mem = parts[4] if len(parts) > 4 else ""
                if not name_filter or name_filter.lower() in pname.lower():
                    results.append(f"{pid:>6}  {pname:<30} {mem}")
                if len(results) >= max_results:
                    results.append(f"...(截断至 {max_results} 条)")
                    break
        return "\n".join(results) if results else "(无匹配进程)"
    except Exception as e:
        return f"错误：{e}"


def check_port(port: int) -> str:
    """检测端口占用情况

    迁移来源：tui_agent.py 行 3346-3385
    """
    try:
        import platform
        if platform.system() == "Windows":
            r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
            # 过滤包含指定端口的行
            lines = [line for line in r.stdout.splitlines() if f":{port} " in line]
            if not lines:
                return f"端口 {port} 未被占用"
            result = [f"端口 {port} 已被占用："]
            for line in lines[:5]:
                parts = line.split()
                if len(parts) >= 4:
                    result.append(f"  协议: {parts[0]}, 本地地址: {parts[1]}, 状态: {parts[2]}, PID: {parts[3]}")
            return "\n".join(result)
        else:
            r = subprocess.run(["lsof", "-i", f":{port}"], capture_output=True, text=True, timeout=10)
            if not r.stdout.strip():
                return f"端口 {port} 未被占用"
            return f"端口 {port} 已被占用：\n{r.stdout.strip()[:2000]}"
    except subprocess.TimeoutExpired:
        return "错误：检测超时"
    except Exception as e:
        return f"错误：{e}"
