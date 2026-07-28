"""安全审计工具

迁移来源：tui_agent.py 行 3595-3957

提供以下纯函数：
- scan_code_vulnerabilities：扫描代码文件中的安全漏洞
- detect_sensitive_info：检测代码中的敏感信息泄露
- _scan_file_secrets：扫描单个文件中的敏感信息
- check_dependencies_vulnerabilities：检查Python依赖包的已知漏洞
- check_config_security：检查配置文件安全
- security_audit：综合安全审计

依赖：
- zeroai.core.constants：MAX_FILE_SIZE
- .file_manager._load_svg_icon：图标标签
- 标准库：os, re, subprocess, sys, pathlib
"""
import os
import re
import subprocess
import sys
from pathlib import Path

from zeroai.core.constants import MAX_FILE_SIZE
from .file_manager import _load_svg_icon


# 工作目录（用于查找 requirements.txt 等项目文件）
WORK_DIR = os.getcwd()


# 漏洞模式规则表
# 迁移来源：tui_agent.py 行 3595-3647
VULN_PATTERNS = [
    # SQL注入
    {"id": "SQLI001", "severity": "高", "category": "SQL注入",
     "pattern": r'execute\s*\(\s*["\'].*\+.*["\']\s*\)|execute\s*\(\s*f["\']',
     "desc": "SQL拼接执行，可能导致SQL注入", "fix": "使用参数化查询：cursor.execute('SELECT * FROM t WHERE id=?', (id,))"},
    {"id": "SQLI002", "severity": "高", "category": "SQL注入",
     "pattern": r'\.raw\s*\(\s*["\'].*\+.*["\']\s*\)|\.raw\s*\(\s*f["\']',
     "desc": "ORM raw查询拼接，可能导致SQL注入", "fix": "使用ORM参数绑定或参数化查询"},
    # XSS
    {"id": "XSS001", "severity": "中", "category": "XSS",
     "pattern": r'innerHTML\s*=\s*[^"\']*\+|innerHTML\s*=\s*`',
     "desc": "innerHTML直接拼接，可能导致XSS", "fix": "使用textContent或对内容进行HTML转义"},
    {"id": "XSS002", "severity": "中", "category": "XSS",
     "pattern": r'dangerouslySetInnerHTML',
     "desc": "React dangerouslySetInnerHTML，可能导致XSS", "fix": "避免使用dangerouslySetInnerHTML，或对内容严格转义"},
    # 命令注入
    {"id": "CMD001", "severity": "高", "category": "命令注入",
     "pattern": r'os\.system\s*\(\s*[^"\']*["\'].*\+|os\.system\s*\(\s*f["\']',
     "desc": "os.system拼接执行，可能导致命令注入", "fix": "使用subprocess.run(args_list)避免shell=True"},
    {"id": "CMD002", "severity": "高", "category": "命令注入",
     "pattern": r'subprocess\..*shell\s*=\s*True',
     "desc": "subprocess shell=True，可能导致命令注入", "fix": "使用shell=False并传递参数列表"},
    # 路径穿越
    {"id": "PATH001", "severity": "中", "category": "路径穿越",
     "pattern": r'open\s*\(\s*request\.|open\s*\(\s*input\s*\(',
     "desc": "直接打开用户输入路径，可能导致路径穿越", "fix": "验证路径在允许目录内：Path(path).resolve()检查是否在WORK_DIR下"},
    # 硬编码密钥
    {"id": "KEY001", "severity": "高", "category": "硬编码密钥",
     "pattern": r'(api_key|apikey|api-key|secret|password|passwd|token)\s*=\s*["\'][a-zA-Z0-9_\-]{16,}["\']',
     "desc": "代码中硬编码密钥/密码", "fix": "从环境变量读取：os.environ.get('API_KEY')"},
    {"id": "KEY002", "severity": "高", "category": "硬编码密钥",
     "pattern": r'sk-[a-zA-Z0-9]{20,}',
     "desc": "代码中硬编码API Key（sk-开头）", "fix": "移到环境变量或配置文件中"},
    # 不安全的反序列化
    {"id": "DESER001", "severity": "高", "category": "反序列化",
     "pattern": r'pickle\.loads?\s*\(',
     "desc": "pickle反序列化不安全，可能导致RCE", "fix": "使用json.loads替代，或验证数据来源"},
    # 弱加密
    {"id": "CRYPTO001", "severity": "中", "category": "弱加密",
     "pattern": r'hashlib\.md5\s*\(|hashlib\.sha1\s*\(',
     "desc": "使用MD5/SHA1弱哈希", "fix": "使用SHA256：hashlib.sha256()"},
    {"id": "CRYPTO002", "severity": "高", "category": "弱加密",
     "pattern": r'random\.random\s*\(\s*\).*password|random\.choice.*password',
     "desc": "使用random生成密码（不安全）", "fix": "使用secrets模块：secrets.token_urlsafe()"},
    # 调试代码
    {"id": "DEBUG001", "severity": "低", "category": "调试残留",
     "pattern": r'print\s*\(\s*["\']DEBUG|print\s*\(\s*["\']TODO|breakpoint\s*\(\s*\)',
     "desc": "代码中残留调试语句", "fix": "移除调试代码或使用logging模块"},
    # 不安全的SSL
    {"id": "SSL001", "severity": "中", "category": "SSL",
     "pattern": r'verify\s*=\s*False|CERT_NONE',
     "desc": "禁用SSL证书验证", "fix": "始终验证SSL证书，不要设置verify=False"},
]


def scan_code_vulnerabilities(path: str) -> str:
    """扫描代码文件中的安全漏洞

    迁移来源：tui_agent.py 行 3650-3713
    """
    try:
        full = Path(path).resolve()
        if not full.exists():
            return f"错误：文件不存在 {path}"
        if full.is_dir():
            return f"错误：{path} 是目录，请指定文件"
        if full.stat().st_size > MAX_FILE_SIZE:
            return "错误：文件太大"

        # 读取文件内容
        for enc in ["utf-8", "gbk", "latin-1"]:
            try:
                lines = full.read_text(encoding=enc).splitlines()
                break
            except UnicodeDecodeError:
                continue

        findings = []
        for line_no, line in enumerate(lines, 1):
            for rule in VULN_PATTERNS:
                try:
                    if re.search(rule["pattern"], line, re.IGNORECASE):
                        findings.append({
                            "line": line_no,
                            "id": rule["id"],
                            "severity": rule["severity"],
                            "category": rule["category"],
                            "desc": rule["desc"],
                            "fix": rule["fix"],
                            "code": line.strip()[:100],
                        })
                except Exception:
                    continue

        if not findings:
            return f"{path} 未发现已知漏洞模式\n扫描了 {len(lines)} 行代码，匹配 {len(VULN_PATTERNS)} 条规则"

        # 按严重程度排序
        sev_order = {"高": 0, "中": 1, "低": 2}
        findings.sort(key=lambda x: sev_order.get(x["severity"], 9))

        result = f"{_load_svg_icon('search')} 安全扫描报告：{path}\n"
        result += f"扫描了 {len(lines)} 行代码，发现 {len(findings)} 个问题\n\n"

        # 统计
        high_count = sum(1 for f in findings if f["severity"] == "高")
        mid_count = sum(1 for f in findings if f["severity"] == "中")
        low_count = sum(1 for f in findings if f["severity"] == "低")
        result += f"严重程度：高危 {high_count} | 中危 {mid_count} | 低危 {low_count}\n\n"

        for f in findings[:20]:  # 最多显示20条
            result += f"[{f['severity']}] 第{f['line']}行 ({f['id']} {f['category']})\n"
            result += f"  代码: {f['code']}\n"
            result += f"  问题: {f['desc']}\n"
            result += f"  修复: {f['fix']}\n\n"

        if len(findings) > 20:
            result += f"... 还有 {len(findings) - 20} 个问题未显示\n"

        return result
    except Exception as e:
        return f"错误：{e}"


def _scan_file_secrets(path: str) -> str:
    """扫描单个文件中的敏感信息

    迁移来源：tui_agent.py 行 3742-3787
    """
    SECRET_PATTERNS = [
        (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API Key"),
        (r'sk-or-v1-[a-zA-Z0-9]{20,}', "OpenRouter API Key"),
        (r'AIza[a-zA-Z0-9_\-]{35}', "Google API Key"),
        (r'ghp_[a-zA-Z0-9]{36}', "GitHub Personal Access Token"),
        (r'gho_[a-zA-Z0-9]{36}', "GitHub OAuth Token"),
        (r'glpat-[a-zA-Z0-9_\-]{20}', "GitLab Personal Access Token"),
        (r'AKIA[A-Z0-9]{16}', "AWS Access Key ID"),
        (r'-----BEGIN (RSA |EC |)PRIVATE KEY-----', "私钥"),
        (r'(mysql|mongodb|postgresql|redis)://[^\s"\'<>]+:[^\s"\'<>]+@', "数据库连接字符串（含密码）"),
        (r'(password|passwd|pwd)\s*[=:]\s*["\'][^"\']{4,}["\']', "硬编码密码"),
        (r'(api_key|apikey|api-key|secret_key|secretkey)\s*[=:]\s*["\'][^"\']{8,}["\']', "硬编码API密钥"),
        (r'(token|access_token|auth_token)\s*[=:]\s*["\'][^"\']{16,}["\']', "硬编码Token"),
    ]

    try:
        for enc in ["utf-8", "gbk", "latin-1"]:
            try:
                lines = Path(path).read_text(encoding=enc).splitlines()
                break
            except UnicodeDecodeError:
                continue

        findings = []
        for line_no, line in enumerate(lines, 1):
            for pattern, name in SECRET_PATTERNS:
                try:
                    matches = re.findall(pattern, line, re.IGNORECASE)
                    if matches:
                        # 脱敏显示
                        masked = re.sub(pattern, lambda m: m.group()[:8] + "***" + m.group()[-4:] if len(m.group()) > 12 else "***", line)
                        findings.append(f"  第{line_no}行 [{name}]: {masked.strip()[:120]}")
                except Exception:
                    continue

        if not findings:
            return ""
        result = f"{path}\n"
        result += "\n".join(findings[:15])
        if len(findings) > 15:
            result += f"\n  ... 还有 {len(findings) - 15} 处"
        return result + "\n"
    except Exception:
        return ""


def detect_sensitive_info(path: str) -> str:
    """检测代码中的敏感信息泄露

    迁移来源：tui_agent.py 行 3716-3739
    """
    try:
        full = Path(path).resolve()
        if not full.exists():
            return f"错误：文件不存在 {path}"
        if full.is_dir():
            # 扫描目录下所有文件
            results = []
            extensions = {".py", ".js", ".ts", ".json", ".yaml", ".yml", ".env", ".cfg", ".ini", ".conf", ".txt"}
            for f in full.rglob("*"):
                if f.is_file() and f.suffix.lower() in extensions:
                    if "node_modules" in str(f) or ".git" in str(f):
                        continue
                    r = _scan_file_secrets(str(f))
                    if r and "未发现" not in r:
                        results.append(r)
            if not results:
                return f"{path} 目录下未发现敏感信息泄露"
            return f"{_load_svg_icon('search')} 敏感信息检测报告：{path}\n\n" + "\n".join(results)
        else:
            return _scan_file_secrets(str(full))
    except Exception as e:
        return f"错误：{e}"


def check_dependencies_vulnerabilities() -> str:
    """检查Python依赖包的已知漏洞（使用pip audit或安全检查）

    迁移来源：tui_agent.py 行 3790-3847
    """
    try:
        import subprocess
        import sys as _sys
        # 方法1: 尝试使用 pip-audit（如果安装了）
        try:
            result = subprocess.run(
                [_sys.executable, "-m", "pip_audit"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"{_load_svg_icon('search')} 依赖漏洞检查报告（pip-audit）\n\n{result.stdout[:3000]}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # 方法2: 检查 requirements.txt 中的已知问题包
        req_file = Path(WORK_DIR) / "requirements.txt"
        if not req_file.exists():
            req_file = Path(WORK_DIR) / "pyproject.toml"

        if not req_file.exists():
            return "ℹ 未找到 requirements.txt 或 pyproject.toml，跳过依赖检查\n建议创建 requirements.txt 以启用依赖漏洞检查"

        content = req_file.read_text(encoding="utf-8", errors="replace")

        # 已知有安全问题的包版本（简化版，实际应查询CVE数据库）
        KNOWN_VULN_PACKAGES = {
            "django": {"<2.2.0": "CVE-2019-19844 等多个漏洞", "<3.2.0": "多个安全修复"},
            "flask": {"<1.0": "CVE-2018-1000656"},
            "requests": {"<2.20.0": "CVE-2018-18074"},
            "urllib3": {"<1.24.2": "CVE-2019-11324"},
            "jinja2": {"<2.10.1": "CVE-2019-10906"},
            "cryptography": {"<2.3": "多个安全问题"},
            "pyyaml": {"<5.1": "CVE-2017-18342"},
            "pillow": {"<6.2.0": "多个图像处理漏洞"},
        }

        findings = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 解析包名和版本
            match = re.match(r'^([a-zA-Z0-9_\-]+)\s*[=<>~!]+\s*([0-9.]+)', line)
            if match:
                pkg = match.group(1).lower()
                ver = match.group(2)
                if pkg in KNOWN_VULN_PACKAGES:
                    for vuln_ver, desc in KNOWN_VULN_PACKAGES[pkg].items():
                        findings.append(f"  {pkg}=={ver} → {desc}")

        if not findings:
            return f"未发现已知漏洞依赖\n检查了 {req_file.name}"

        return f"{_load_svg_icon('search')} 依赖漏洞检查报告\n检查文件：{req_file.name}\n\n发现 {len(findings)} 个潜在问题：\n" + "\n".join(findings)
    except Exception as e:
        return f"错误：{e}"


def check_config_security(path: str = ".") -> str:
    """检查配置文件安全

    迁移来源：tui_agent.py 行 3850-3906
    """
    try:
        base = Path(path).resolve()
        if not base.exists():
            return f"错误：路径不存在 {path}"

        findings = []

        # 检查 .env 文件是否暴露
        env_file = base / ".env"
        if env_file.exists():
            # 检查 .env 是否在 .gitignore 中
            gitignore = base / ".gitignore"
            if gitignore.exists():
                gi_content = gitignore.read_text(encoding="utf-8", errors="replace")
                if ".env" not in gi_content:
                    findings.append(".env 文件未被 .gitignore 忽略，可能被提交到版本控制")
            else:
                findings.append("存在 .env 文件但没有 .gitignore，敏感信息可能泄露")
            # 检查 .env 内容
            env_content = env_file.read_text(encoding="utf-8", errors="replace")
            secret_lines = [l for l in env_content.splitlines() if "=" in l and any(k in l.lower() for k in ["key", "secret", "password", "token"])]
            if secret_lines:
                findings.append(f"ℹ .env 包含 {len(secret_lines)} 条敏感配置（KEY/SECRET/PASSWORD/TOKEN）")

        # 检查 .gitignore
        gitignore = base / ".gitignore"
        if not gitignore.exists():
            findings.append("缺少 .gitignore 文件，所有文件都可能被提交到版本控制")

        # 检查日志文件
        for log_file in base.glob("*.log"):
            if log_file.stat().st_size > 0:
                findings.append(f"ℹ 发现日志文件 {log_file.name}（{log_file.stat().st_size} 字节），检查是否包含敏感信息")

        # 检查权限过宽的文件（Windows下检查只读属性）
        for f in base.glob("*"):
            if f.is_file() and f.suffix in (".key", ".pem", ".pfx", ".p12"):
                findings.append(f"发现证书/密钥文件 {f.name}，确保权限设置正确")

        # 检查是否有硬编码IP/端口
        for cfg_file in list(base.glob("*.conf")) + list(base.glob("*.cfg")) + list(base.glob("*.ini")):
            try:
                content = cfg_file.read_text(encoding="utf-8", errors="replace")
                ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', content)
                if ips:
                    findings.append(f"ℹ {cfg_file.name} 包含IP地址：{', '.join(set(ips)[:5])}")
            except Exception:
                continue

        if not findings:
            return f"{path} 配置安全检查通过\n检查项：.env/.gitignore/日志文件/证书文件/IP暴露"

        return f"{_load_svg_icon('search')} 配置安全检查报告：{path}\n\n发现 {len(findings)} 个注意事项：\n" + "\n".join(f"  {i+1}. {f}" for i, f in enumerate(findings))
    except Exception as e:
        return f"错误：{e}"


def security_audit(path: str = ".", scan_type: str = "all") -> str:
    """综合安全审计
    scan_type: all(全部) / code(代码漏洞) / secret(敏感信息) / deps(依赖漏洞) / config(配置安全)

    迁移来源：tui_agent.py 行 3909-3956
    """
    try:
        target = Path(path).resolve()
        results = []

        if scan_type in ("all", "code"):
            results.append("═══ 代码漏洞扫描 ═══")
            if target.is_dir():
                # 扫描目录下所有代码文件
                code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".php", ".java", ".go"}
                count = 0
                for f in target.rglob("*"):
                    if f.is_file() and f.suffix.lower() in code_exts:
                        if "node_modules" in str(f) or ".git" in str(f) or "__pycache__" in str(f):
                            continue
                        r = scan_code_vulnerabilities(str(f))
                        if r and "未发现" not in r:
                            results.append(r)
                            count += 1
                    if count >= 10:
                        results.append(f"... 目录较大，仅扫描前10个有问题的文件")
                        break
                if count == 0:
                    results.append(f"{path} 目录下代码文件未发现已知漏洞模式")
            else:
                results.append(scan_code_vulnerabilities(str(target)))
            results.append("")

        if scan_type in ("all", "secret"):
            results.append("═══ 敏感信息检测 ═══")
            results.append(detect_sensitive_info(str(target)))
            results.append("")

        if scan_type in ("all", "deps"):
            results.append("═══ 依赖漏洞检查 ═══")
            results.append(check_dependencies_vulnerabilities())
            results.append("")

        if scan_type in ("all", "config"):
            results.append("═══ 配置安全检查 ═══")
            results.append(check_config_security(str(target) if target.is_dir() else str(target.parent)))

        return "\n".join(results)
    except Exception as e:
        return f"安全审计出错：{e}"
