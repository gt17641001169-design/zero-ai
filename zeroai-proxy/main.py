"""
ZeroAI 代理服务器（多上游路由版 · 安全加固版）
=================================================
保护所有 API Key 的核心组件。

工作原理：
1. 客户端（ZeroAI TUI）请求本代理 → 携带客户端 Token
2. 代理验证 Token + 限流 + 模型白名单 + 暴力破解防护
3. 根据模型名自动路由到对应上游：
   - glm-*       → 智谱 GLM
   - *:free      → OpenRouter
   - nvidia/*    → OpenRouter
4. 注入真实 API Key 转发 → 流式透传响应

所有真实 Key 只存在于服务器 .env，客户端永远拿不到。

安全加固特性（v1.2.0）：
- Token 归属+用量统计（每个 Token 绑定用户/团队，记录调用量）
- Token 吊销机制（修改 tokens.json 即时生效，无需重启）
- Token 过期时间（支持永久或指定过期时间）
- 暴力破解防护（同一 IP 连续失败 N 次自动封禁 X 分钟）
- HTTPS 自签证书支持（Token 加密传输，防中间人嗅探）
- 关闭 /docs 和 /redoc（避免泄露 API 文档）
- /admin 管理端点（查看/吊销 Token，查看封禁列表）
- 审计日志（记录所有访问和操作，IP 脱敏）
"""

import os
import time
import json
import asyncio
import logging
import threading
from collections import defaultdict, deque
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
import httpx

# ====== 配置加载 ======
load_dotenv()

# ====== 多上游配置 ======
# 上游 1：智谱 GLM
GLM_BASE_URL = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
GLM_API_KEY = os.getenv("GLM_API_KEY", "")

# 上游 2：OpenRouter
OR_BASE_URL = os.getenv("OR_BASE_URL", "https://openrouter.ai/api/v1")
OR_API_KEY = os.getenv("OR_API_KEY", "")

# 上游超时
UPSTREAM_TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "120"))

# ====== 代理服务监听 ======
PROXY_HOST = os.getenv("PROXY_HOST", "0.0.0.0")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8000"))

# ====== HTTPS 配置（自签证书）======
# 启用 HTTPS 后 Token 加密传输，防中间人嗅探
# 生成自签证书：openssl req -x509 -newkey rsa:4096 -keyout cert.key -out cert.pem -days 365 -nodes -subj "/CN=zeroai-proxy"
SSL_CERT_FILE = os.getenv("SSL_CERT_FILE", "")  # 证书文件路径（如 ./cert.pem）
SSL_KEY_FILE = os.getenv("SSL_KEY_FILE", "")    # 私钥文件路径（如 ./cert.key）

# ====== 客户端访问 Token ======
# 兼容旧模式：从环境变量加载简单 Token（无归属信息）
CLIENT_TOKENS = {t.strip() for t in os.getenv("CLIENT_TOKENS", "").split(",") if t.strip()}

# ====== Token 元数据文件（推荐模式）======
# JSON 文件存储 Token 完整信息：归属、团队、过期时间、吊销状态、用量统计
# 修改此文件后自动热重载，无需重启服务
TOKENS_FILE = os.getenv("TOKENS_FILE", "tokens.json")

# ====== 管理员 Token（用于 /admin 端点）======
# 用于查看/吊销 Token、查看封禁列表等管理操作
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# ====== 暴力破解防护 ======
# 同一 IP 在 BAN_WINDOW_MINUTES 内连续失败 MAX_FAILURES 次后封禁 BAN_MINUTES 分钟
MAX_FAILURES = int(os.getenv("MAX_FAILURES", "5"))      # 最大失败次数
BAN_MINUTES = int(os.getenv("BAN_MINUTES", "30"))        # 封禁时长（分钟）
BAN_WINDOW_MINUTES = int(os.getenv("BAN_WINDOW_MINUTES", "10"))  # 失败计数窗口（分钟）

# ====== 限流 ======
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))

# ====== 模型白名单（全部免费模型）======
ALLOWED_MODELS = {
    m.strip() for m in os.getenv(
        "ALLOWED_MODELS",
        # 智谱免费
        "glm-4.7-flash,glm-4-flash,glm-4v-flash,"
        # OpenRouter 免费（推理 + 中文写作专家使用）
        "nvidia/nemotron-3-ultra-550b-a55b:free,nvidia/nemotron-3-nano-30b-a3b:free,"
        # OpenRouter 自动路由免费
        "openrouter/free"
    ).split(",") if m.strip()
}

# ====== 日志 ======
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("zeroai-proxy")

# ====== FastAPI ======
# 安全加固：关闭 /docs 和 /redoc，避免泄露 API 文档
app = FastAPI(
    title="ZeroAI Proxy",
    description="保护 API Key 的多上游代理服务",
    version="1.2.0",
    docs_url=None,       # 关闭 Swagger UI
    redoc_url=None,      # 关闭 ReDoc
    openapi_url=None,    # 关闭 OpenAPI schema（防止 /openapi.json 泄露）
)

security = HTTPBearer()


# ====== 限流器 ======
class RateLimiter:
    """每 IP 滑动窗口限流"""
    def __init__(self, max_per_min: int):
        self.max_per_min = max_per_min
        self.records: dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, client_ip: str) -> bool:
        async with self._lock:
            now = time.time()
            window = self.records[client_ip]
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= self.max_per_min:
                return False
            window.append(now)
            return True

rate_limiter = RateLimiter(RATE_LIMIT_PER_MIN)


# ====== Token 管理器（归属+统计+吊销+热重载）======
class TokenManager:
    """Token 元数据管理，支持归属、用量统计、吊销、过期、热重载。

    Token 文件格式（tokens.json）：
    {
      "abc123...": {
        "user": "张三",
        "team": "开发团队",
        "revoked": false,
        "expires": null,              // null=永久，"2026-12-31T23:59:59"=指定过期
        "usage_count": 0,             // 程序自动更新
        "last_used": null,            // 程序自动更新
        "created_at": "2026-07-25..."
      }
    }

    兼容模式：如果 tokens.json 不存在，从 CLIENT_TOKENS 环境变量加载（无归属信息）。
    """

    def __init__(self, tokens_file: str, fallback_tokens: set):
        self.tokens_file = tokens_file
        self.fallback_tokens = fallback_tokens
        self.tokens: dict = {}
        self._last_load_mtime = 0
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """加载 Token 文件，支持热重载（检测 mtime 变化自动重新加载）"""
        try:
            if not os.path.exists(self.tokens_file):
                # 文件不存在，用 fallback
                if self.fallback_tokens:
                    self.tokens = {
                        t: {
                            "user": "anonymous",
                            "team": "未知",
                            "revoked": False,
                            "expires": None,
                            "usage_count": 0,
                            "last_used": None,
                            "created_at": None,
                        }
                        for t in self.fallback_tokens
                    }
                    logger.info(f"📋 Token 模式：环境变量（{len(self.tokens)} 个，无归属信息）")
                else:
                    self.tokens = {}
                    logger.warning("⚠️  无可用 Token（tokens.json 和 CLIENT_TOKENS 均未配置）")
                return

            # 检查 mtime，没变化则跳过
            mtime = os.path.getmtime(self.tokens_file)
            if mtime == self._last_load_mtime and self.tokens:
                return

            with open(self.tokens_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 保留运行时的 usage_count/last_used（避免热重载时统计归零）
            old_tokens = self.tokens
            new_tokens = {}
            for token, meta in data.items():
                # 跳过以 _ 开头的注释键（如 _说明 / _字段说明 / _生成方式）
                # 这些是 tokens.json.example 中的文档字段，不能作为有效 Token
                if not isinstance(token, str) or token.startswith("_"):
                    continue
                if not isinstance(meta, dict):
                    continue
                # 保留旧的统计数据
                old_meta = old_tokens.get(token, {})
                new_tokens[token] = {
                    "user": meta.get("user", "anonymous"),
                    "team": meta.get("team", "未知"),
                    "revoked": meta.get("revoked", False),
                    "expires": meta.get("expires"),  # None 或 ISO 字符串
                    "usage_count": old_meta.get("usage_count", 0) if old_meta else meta.get("usage_count", 0),
                    "last_used": old_meta.get("last_used") if old_meta else meta.get("last_used"),
                    "created_at": meta.get("created_at"),
                }

            self.tokens = new_tokens
            self._last_load_mtime = mtime
            logger.info(f"📋 Token 已加载（{len(self.tokens)} 个，来源：{self.tokens_file}）")

        except json.JSONDecodeError as e:
            logger.error(f"❌ tokens.json 格式错误: {e}")
        except Exception as e:
            logger.error(f"❌ 加载 Token 失败: {e}")

    def _maybe_reload(self):
        """检查是否需要热重载"""
        try:
            if os.path.exists(self.tokens_file):
                mtime = os.path.getmtime(self.tokens_file)
                if mtime != self._last_load_mtime:
                    logger.info("🔄 检测到 tokens.json 变更，热重载中...")
                    self._load()
        except Exception:
            pass

    def verify(self, token: str) -> tuple:
        """验证 Token，返回 (是否有效, 原因, 元数据)

        Returns:
            (True, "ok", meta) - 验证通过
            (False, "not_found", None) - Token 不存在
            (False, "revoked", None) - Token 已吊销
            (False, "expired", None) - Token 已过期
        """
        with self._lock:
            self._maybe_reload()

            if token not in self.tokens:
                return False, "not_found", None

            meta = self.tokens[token]

            if meta.get("revoked", False):
                return False, "revoked", meta

            # 检查过期时间
            expires = meta.get("expires")
            if expires:
                try:
                    exp_dt = datetime.fromisoformat(expires)
                    if datetime.now() > exp_dt:
                        return False, "expired", meta
                except (ValueError, TypeError):
                    pass  # 过期时间格式错误，忽略

            return True, "ok", meta

    def record_usage(self, token: str):
        """记录 Token 使用（调用计数 + 最后使用时间）"""
        with self._lock:
            if token in self.tokens:
                self.tokens[token]["usage_count"] = self.tokens[token].get("usage_count", 0) + 1
                self.tokens[token]["last_used"] = datetime.now().isoformat()

    def list_tokens(self) -> list:
        """列出所有 Token（脱敏：只显示前 8 字符）"""
        with self._lock:
            self._maybe_reload()
            result = []
            for token, meta in self.tokens.items():
                result.append({
                    "token_preview": token[:8] + "..." + token[-4:] if len(token) > 12 else token[:8] + "...",
                    "user": meta.get("user", "anonymous"),
                    "team": meta.get("team", "未知"),
                    "revoked": meta.get("revoked", False),
                    "expires": meta.get("expires"),
                    "usage_count": meta.get("usage_count", 0),
                    "last_used": meta.get("last_used"),
                    "created_at": meta.get("created_at"),
                })
            return result

    def revoke(self, token: str) -> bool:
        """吊销 Token（写入文件，立即生效）"""
        with self._lock:
            if token not in self.tokens:
                return False
            self.tokens[token]["revoked"] = True
            self._save()
            logger.warning(f"🚫 Token 已吊销: {token[:8]}... (user={self.tokens[token].get('user')})")
            return True

    def reinstate(self, token: str) -> bool:
        """恢复已吊销的 Token"""
        with self._lock:
            if token not in self.tokens:
                return False
            self.tokens[token]["revoked"] = False
            self._save()
            logger.info(f"✅ Token 已恢复: {token[:8]}... (user={self.tokens[token].get('user')})")
            return True

    def reset_stats(self, token: str) -> bool:
        """重置 Token 用量统计"""
        with self._lock:
            if token not in self.tokens:
                return False
            self.tokens[token]["usage_count"] = 0
            self.tokens[token]["last_used"] = None
            self._save()
            return True

    def _save(self):
        """保存 Token 到文件"""
        try:
            with open(self.tokens_file, "w", encoding="utf-8") as f:
                json.dump(self.tokens, f, ensure_ascii=False, indent=2)
            self._last_load_mtime = os.path.getmtime(self.tokens_file)
        except Exception as e:
            logger.error(f"❌ 保存 tokens.json 失败: {e}")


token_manager = TokenManager(TOKENS_FILE, CLIENT_TOKENS)


# ====== 暴力破解防护 ======
class IPBanner:
    """IP 暴力破解防护：同一 IP 在窗口期内连续失败 N 次后封禁 X 分钟。

    - 失败计数窗口：BAN_WINDOW_MINUTES（默认 10 分钟）
    - 封禁阈值：MAX_FAILURES（默认 5 次）
    - 封禁时长：BAN_MINUTES（默认 30 分钟）
    - 验证成功后清除该 IP 的失败记录
    """

    def __init__(self, max_failures: int, ban_minutes: int, window_minutes: int):
        self.max_failures = max_failures
        self.ban_minutes = ban_minutes
        self.window_seconds = window_minutes * 60
        self.ban_seconds = ban_minutes * 60
        self.failures: dict = defaultdict(deque)  # {ip: deque([失败时间戳])}
        self.banned: dict = {}  # {ip: 封禁到期时间戳}
        self._lock = threading.Lock()

    def is_banned(self, ip: str) -> tuple:
        """检查 IP 是否被封禁。返回 (是否封禁, 剩余秒数)"""
        with self._lock:
            if ip not in self.banned:
                return False, 0
            ban_until = self.banned[ip]
            now = time.time()
            if now >= ban_until:
                # 封禁已过期，清除
                del self.banned[ip]
                self.failures.pop(ip, None)
                return False, 0
            remaining = int(ban_until - now)
            return True, remaining

    def record_failure(self, ip: str) -> bool:
        """记录失败。返回是否触发封禁。"""
        with self._lock:
            now = time.time()
            window = self.failures[ip]

            # 清除窗口外的旧记录
            while window and now - window[0] > self.window_seconds:
                window.popleft()

            window.append(now)

            if len(window) >= self.max_failures:
                self.banned[ip] = now + self.ban_seconds
                logger.warning(
                    f"🚫 IP 已封禁: {self._mask_ip(ip)} "
                    f"(失败 {len(window)} 次，封禁 {self.ban_minutes} 分钟)"
                )
                return True
            return False

    def clear_failures(self, ip: str):
        """验证成功后清除失败记录"""
        with self._lock:
            self.failures.pop(ip, None)

    def list_banned(self) -> list:
        """列出当前封禁的 IP（脱敏）"""
        with self._lock:
            now = time.time()
            result = []
            for ip, ban_until in list(self.banned.items()):
                if now >= ban_until:
                    del self.banned[ip]
                    continue
                result.append({
                    "ip_masked": self._mask_ip(ip),
                    "remaining_seconds": int(ban_until - now),
                    "failures": len(self.failures.get(ip, [])),
                })
            return result

    @staticmethod
    def _mask_ip(ip: str) -> str:
        """IP 脱敏：192.168.1.100 → 192.168.***.***"""
        parts = ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.***.***"
        return ip[:4] + "***"


ip_banner = IPBanner(MAX_FAILURES, BAN_MINUTES, BAN_WINDOW_MINUTES)


# ====== 模型路由 ======
def route_upstream(model: str) -> tuple[str, str]:
    """
    根据模型名返回 (base_url, api_key)
    路由规则：
      - glm-*               → 智谱 GLM
      - *:free              → OpenRouter
      - nvidia/*            → OpenRouter
      - openrouter/*        → OpenRouter
      - meta-llama/*        → OpenRouter
      - google/*            → OpenRouter
      - mistralai/*         → OpenRouter
      - qwen/*              → OpenRouter
      - 默认                → OpenRouter（保守，避免误用付费模型）
    """
    m = model.lower()
    # 智谱 GLM 系列
    if m.startswith("glm-"):
        return GLM_BASE_URL, GLM_API_KEY
    # OpenRouter 免费模型特征
    if (
        m.endswith(":free")
        or m.startswith("nvidia/")
        or m.startswith("openrouter/")
        or m.startswith("meta-llama/")
        or m.startswith("google/")
        or m.startswith("mistralai/")
        or m.startswith("qwen/")
        or m.startswith("deepseek/")
        or m.startswith("microsoft/")
    ):
        return OR_BASE_URL, OR_API_KEY
    # 默认走 OpenRouter（白名单已过滤，到这里都是允许的）
    return OR_BASE_URL, OR_API_KEY


# ====== 鉴权（集成 TokenManager + IPBanner）======
async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """验证客户端 Token（含暴力破解防护、归属记录、用量统计）

    Returns:
        Token 元数据 dict（含 user, team 等）

    Raises:
        HTTPException 403 - IP 已被封禁
        HTTPException 401 - Token 无效/已吊销/已过期
    """
    client_ip = request.client.host if request.client else "unknown"

    # 1. 检查 IP 是否被封禁（暴力破解防护）
    is_banned, remaining = ip_banner.is_banned(client_ip)
    if is_banned:
        logger.warning(f"🚫 封禁 IP 访问被拒: {ip_banner._mask_ip(client_ip)} (剩余 {remaining}s)")
        raise HTTPException(
            status_code=403,
            detail=f"IP banned due to too many failures. Retry in {remaining} seconds."
        )

    token = credentials.credentials

    # 2. 无 Token 配置时（仅限内网调试）
    if not token_manager.tokens:
        logger.warning("⚠️  无可用 Token，代理处于无鉴权模式（仅限内网调试）")
        return {"user": "anonymous", "team": "调试"}

    # 3. 验证 Token
    valid, reason, meta = token_manager.verify(token)
    if not valid:
        # 记录失败（可能触发封禁）
        triggered_ban = ip_banner.record_failure(client_ip)
        if reason == "not_found":
            logger.warning(f"❌ 无效 Token: {token[:8]}... ip={ip_banner._mask_ip(client_ip)}")
            detail = "Invalid token"
        elif reason == "revoked":
            logger.warning(f"🚫 已吊销 Token 访问: {token[:8]}... ip={ip_banner._mask_ip(client_ip)}")
            detail = "Token has been revoked"
        elif reason == "expired":
            logger.warning(f"⏰ 已过期 Token 访问: {token[:8]}... ip={ip_banner._mask_ip(client_ip)}")
            detail = "Token has expired"
        else:
            detail = "Token verification failed"

        if triggered_ban:
            detail += f". IP has been banned for {BAN_MINUTES} minutes due to repeated failures."

        raise HTTPException(status_code=401, detail=detail)

    # 4. 验证成功，清除失败记录
    ip_banner.clear_failures(client_ip)

    # 5. 记录用量
    token_manager.record_usage(token)

    return meta or {"user": "anonymous", "team": "未知"}


# ====== 管理员鉴权 ======
async def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """验证管理员 Token（用于 /admin 端点）"""
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin endpoint disabled (ADMIN_TOKEN not configured)")
    if credentials.credentials != ADMIN_TOKEN:
        logger.warning(f"❌ 管理端点鉴权失败: {credentials.credentials[:8]}...")
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return "admin"


# ====== 健康检查 ======
@app.get("/health")
async def health():
    """健康检查（不上报 Key，不上报 Token 详情）"""
    return {
        "status": "ok",
        "version": "1.2.0",
        "upstreams": {
            "glm": {"base_url": GLM_BASE_URL, "configured": bool(GLM_API_KEY)},
            "openrouter": {"base_url": OR_BASE_URL, "configured": bool(OR_API_KEY)},
        },
        "tokens_count": len(token_manager.tokens),
        "allowed_models_count": len(ALLOWED_MODELS),
        "https_enabled": bool(SSL_CERT_FILE and SSL_KEY_FILE),
        "banned_ips_count": len(ip_banner.banned),
    }


@app.get("/")
async def root():
    """根路径（最小信息，不暴露 docs）"""
    return {"name": "ZeroAI Proxy", "version": "1.2.0"}


# ====== 核心代理：OpenAI 兼容端点 ======
@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    token_meta: dict = Depends(verify_token),
):
    """转发 chat/completions 到对应上游（根据模型名路由）"""

    # 1. 限流
    client_ip = request.client.host if request.client else "unknown"
    if not await rate_limiter.check(client_ip):
        logger.warning(f"⚠️  限流触发 ip={ip_banner._mask_ip(client_ip)} user={token_meta.get('user')}")
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # 2. 解析请求体
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 3. 模型白名单检查
    model = body.get("model", "")
    if ALLOWED_MODELS and model not in ALLOWED_MODELS:
        logger.warning(f"❌ 模型不在白名单: {model}")
        raise HTTPException(
            status_code=403,
            detail=f"Model '{model}' not allowed. Allowed: {sorted(ALLOWED_MODELS)}"
        )

    # 4. 路由到对应上游
    upstream_url_base, upstream_key = route_upstream(model)
    upstream_url = f"{upstream_url_base}/chat/completions"

    if not upstream_key:
        logger.error(f"❌ 上游 Key 未配置 model={model}")
        raise HTTPException(status_code=500, detail=f"Upstream key not configured for model {model}")

    # 5. 构造上游请求头
    headers = {
        "Authorization": f"Bearer {upstream_key}",
        "Content-Type": "application/json",
    }
    # OpenRouter 额外需要这些头（建议但不强制）
    if "openrouter.ai" in upstream_url_base:
        headers["HTTP-Referer"] = os.getenv("OR_REFERER", "https://zeroai.local")
        headers["X-Title"] = "ZeroAI Proxy"

    # 6. 流式标志
    stream = bool(body.get("stream", False))

    # 标记上游类型用于日志
    upstream_label = "GLM" if "bigmodel" in upstream_url_base else "OR"
    user = token_meta.get("user", "anonymous")
    team = token_meta.get("team", "未知")
    logger.info(f"→ model={model} upstream={upstream_label} stream={stream} ip={ip_banner._mask_ip(client_ip)} user={user} team={team}")

    # 7. 非流式
    if not stream:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            try:
                resp = await client.post(upstream_url, headers=headers, json=body)
                resp.raise_for_status()
                logger.info(f"← {upstream_label} status={resp.status_code} bytes={len(resp.content)}")
                return JSONResponse(content=resp.json(), status_code=resp.status_code)
            except httpx.HTTPStatusError as e:
                logger.error(f"❌ {upstream_label} 上游错误: {e.response.status_code} {e.response.text[:200]}")
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Upstream error: {e.response.text[:500]}"
                )
            except httpx.RequestError as e:
                logger.error(f"❌ {upstream_label} 网络错误: {e}")
                raise HTTPException(status_code=502, detail=f"Network error: {str(e)}")

    # 8. 流式：SSE 透传
    async def stream_generator():
        timeout = httpx.Timeout(UPSTREAM_TIMEOUT, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                async with client.stream("POST", upstream_url, headers=headers, json=body) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        logger.error(f"❌ {upstream_label} 流式错误: {resp.status_code} {error_body[:200]}")
                        yield f"data: {json.dumps({'error': f'Upstream {resp.status_code}', 'detail': error_body.decode('utf-8', errors='ignore')[:500]})}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    bytes_sent = 0
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            bytes_sent += len(chunk)
                            yield chunk
                    logger.info(f"← {upstream_label} stream done bytes={bytes_sent}")
            except httpx.RequestError as e:
                logger.error(f"❌ {upstream_label} 流式网络错误: {e}")
                yield f"data: {json.dumps({'error': f'Network error: {str(e)}'})}\n\n"
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ====== 模型列表端点 ======
@app.get("/v1/models")
async def list_models(token: str = Depends(verify_token)):
    """返回允许的模型列表（OpenAI 兼容）"""
    now = int(time.time())
    models = []
    for m in sorted(ALLOWED_MODELS):
        # 标记上游
        if m.lower().startswith("glm-"):
            owner = "zhipu"
        else:
            owner = "openrouter"
        models.append({
            "id": m,
            "object": "model",
            "created": now,
            "owned_by": owner,
        })
    return {"object": "list", "data": models}


# ====== 管理端点（需 ADMIN_TOKEN）======
@app.get("/admin/tokens")
async def admin_list_tokens(_: str = Depends(verify_admin_token)):
    """列出所有 Token（脱敏显示，含用量统计）"""
    return {"tokens": token_manager.list_tokens(), "total": len(token_manager.tokens)}


@app.post("/admin/tokens/{token}/revoke")
async def admin_revoke_token(token: str, _: str = Depends(verify_admin_token)):
    """吊销指定 Token（立即生效，无需重启服务）"""
    if token_manager.revoke(token):
        return {"status": "ok", "message": f"Token {token[:8]}... 已吊销"}
    raise HTTPException(status_code=404, detail="Token not found")


@app.post("/admin/tokens/{token}/reinstate")
async def admin_reinstate_token(token: str, _: str = Depends(verify_admin_token)):
    """恢复已吊销的 Token"""
    if token_manager.reinstate(token):
        return {"status": "ok", "message": f"Token {token[:8]}... 已恢复"}
    raise HTTPException(status_code=404, detail="Token not found")


@app.post("/admin/tokens/{token}/reset-stats")
async def admin_reset_token_stats(token: str, _: str = Depends(verify_admin_token)):
    """重置 Token 用量统计"""
    if token_manager.reset_stats(token):
        return {"status": "ok", "message": f"Token {token[:8]}... 统计已重置"}
    raise HTTPException(status_code=404, detail="Token not found")


@app.get("/admin/banned")
async def admin_list_banned(_: str = Depends(verify_admin_token)):
    """列出当前被封禁的 IP（脱敏）"""
    return {"banned_ips": ip_banner.list_banned(), "total": len(ip_banner.banned)}


@app.get("/admin/status")
async def admin_status(_: str = Depends(verify_admin_token)):
    """服务器状态概览"""
    return {
        "version": "1.2.0",
        "tokens_total": len(token_manager.tokens),
        "tokens_active": sum(1 for t in token_manager.tokens.values() if not t.get("revoked")),
        "tokens_revoked": sum(1 for t in token_manager.tokens.values() if t.get("revoked")),
        "banned_ips": len(ip_banner.banned),
        "rate_limit_per_min": RATE_LIMIT_PER_MIN,
        "https_enabled": bool(SSL_CERT_FILE and SSL_KEY_FILE),
        "max_failures": MAX_FAILURES,
        "ban_minutes": BAN_MINUTES,
        "allowed_models": sorted(ALLOWED_MODELS),
    }


# ====== 启动入口 ======
if __name__ == "__main__":
    import uvicorn
    import sys

    # HTTPS 配置
    use_https = bool(SSL_CERT_FILE and SSL_KEY_FILE and os.path.exists(SSL_CERT_FILE) and os.path.exists(SSL_KEY_FILE))

    logger.info("=" * 60)
    logger.info("ZeroAI Proxy 启动中（安全加固版 v1.2.0）...")
    logger.info(f"  监听: {PROXY_HOST}:{PROXY_PORT} ({'HTTPS' if use_https else 'HTTP'})")
    if use_https:
        logger.info(f"  证书: {SSL_CERT_FILE}")
        logger.info(f"  私钥: {SSL_KEY_FILE}")
    else:
        logger.warning("  ⚠️  HTTPS 未启用，Token 将明文传输（建议配置 SSL_CERT_FILE 和 SSL_KEY_FILE）")
    logger.info(f"  GLM 上游: {GLM_BASE_URL} (Key 已配置: {bool(GLM_API_KEY)})")
    logger.info(f"  OR  上游: {OR_BASE_URL} (Key 已配置: {bool(OR_API_KEY)})")
    logger.info(f"  客户端 Token 数: {len(token_manager.tokens)} (来源: {TOKENS_FILE if os.path.exists(TOKENS_FILE) else 'CLIENT_TOKENS 环境变量'})")
    logger.info(f"  管理端点: {'✅ 已启用' if ADMIN_TOKEN else '❌ 未启用 (ADMIN_TOKEN 未配置)'}")
    logger.info(f"  限流: {RATE_LIMIT_PER_MIN}/分钟/IP")
    logger.info(f"  暴力破解防护: 失败 {MAX_FAILURES} 次封禁 {BAN_MINUTES} 分钟（窗口 {BAN_WINDOW_MINUTES} 分钟）")
    logger.info(f"  允许模型 ({len(ALLOWED_MODELS)} 个):")
    for m in sorted(ALLOWED_MODELS):
        upstream = "GLM" if m.lower().startswith("glm-") else "OR "
        logger.info(f"    [{upstream}] {m}")
    logger.info("=" * 60)
    if not GLM_API_KEY and not OR_API_KEY:
        logger.error("❌ GLM_API_KEY 和 OR_API_KEY 都未配置，请检查 .env")

    # Windows 服务模式兼容性修复：
    # 1. NSSM 服务模式下 stdin 为 None/closed，uvicorn 信号处理会立即触发关闭
    # 2. 禁用 uvicorn 的 signal handlers，由 NSSM 通过 SIGTERM 直接终止进程
    # 3. 重定向 stdin 到 devnull，防止 EOF 触发退出
    try:
        if sys.stdin is None or (hasattr(sys.stdin, 'closed') and sys.stdin.closed):
            sys.stdin = open(os.devnull, 'r')
    except Exception:
        pass

    # 构造 uvicorn 配置（含 HTTPS 支持）
    config_kwargs = {
        "host": PROXY_HOST,
        "port": PROXY_PORT,
        "log_level": "info",
        "loop": "asyncio",
    }
    if use_https:
        config_kwargs["ssl_certfile"] = SSL_CERT_FILE
        config_kwargs["ssl_keyfile"] = SSL_KEY_FILE

    config = uvicorn.Config(app, **config_kwargs)
    server = uvicorn.Server(config)
    # 关键：禁用 signal handlers，防止 Windows 服务模式下误触发关闭
    server.install_signal_handlers = lambda: None
    server.run()
