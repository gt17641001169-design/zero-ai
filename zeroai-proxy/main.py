"""
ZeroAI 代理服务器（多上游路由版）
=================================
保护所有 API Key 的核心组件。

工作原理：
1. 客户端（ZeroAI TUI）请求本代理 → 携带客户端 Token
2. 代理验证 Token + 限流 + 模型白名单
3. 根据模型名自动路由到对应上游：
   - glm-*       → 智谱 GLM
   - *:free      → OpenRouter
   - nvidia/*    → OpenRouter
4. 注入真实 API Key 转发 → 流式透传响应

所有真实 Key 只存在于服务器 .env，客户端永远拿不到。
"""

import os
import time
import json
import asyncio
import logging
from collections import defaultdict, deque

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

# ====== 客户端访问 Token ======
CLIENT_TOKENS = {t.strip() for t in os.getenv("CLIENT_TOKENS", "").split(",") if t.strip()}

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
app = FastAPI(
    title="ZeroAI Proxy",
    description="保护 API Key 的多上游代理服务",
    version="1.1.0",
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


# ====== 鉴权 ======
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """验证客户端 Token"""
    token = credentials.credentials
    if not CLIENT_TOKENS:
        logger.warning("⚠️  CLIENT_TOKENS 未配置，代理处于无鉴权模式（仅限内网调试）")
        return "anonymous"
    if token not in CLIENT_TOKENS:
        logger.warning(f"❌ 无效 Token: {token[:8]}...")
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


# ====== 健康检查 ======
@app.get("/health")
async def health():
    """健康检查（不上报 Key）"""
    return {
        "status": "ok",
        "upstreams": {
            "glm": {"base_url": GLM_BASE_URL, "configured": bool(GLM_API_KEY)},
            "openrouter": {"base_url": OR_BASE_URL, "configured": bool(OR_API_KEY)},
        },
        "tokens_count": len(CLIENT_TOKENS),
        "allowed_models_count": len(ALLOWED_MODELS),
    }


@app.get("/")
async def root():
    return {"name": "ZeroAI Proxy", "version": "1.1.0", "docs": "/docs"}


# ====== 核心代理：OpenAI 兼容端点 ======
@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    token: str = Depends(verify_token),
):
    """转发 chat/completions 到对应上游（根据模型名路由）"""

    # 1. 限流
    client_ip = request.client.host if request.client else "unknown"
    if not await rate_limiter.check(client_ip):
        logger.warning(f"⚠️  限流触发 IP={client_ip} token={token[:8]}...")
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
    logger.info(f"→ model={model} upstream={upstream_label} stream={stream} ip={client_ip} token={token[:8]}...")

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


# ====== 启动入口 ======
if __name__ == "__main__":
    import uvicorn
    import sys

    logger.info("=" * 60)
    logger.info("ZeroAI Proxy 启动中（多上游路由版）...")
    logger.info(f"  监听: {PROXY_HOST}:{PROXY_PORT}")
    logger.info(f"  GLM 上游: {GLM_BASE_URL} (Key 已配置: {bool(GLM_API_KEY)})")
    logger.info(f"  OR  上游: {OR_BASE_URL} (Key 已配置: {bool(OR_API_KEY)})")
    logger.info(f"  客户端 Token 数: {len(CLIENT_TOKENS)}")
    logger.info(f"  限流: {RATE_LIMIT_PER_MIN}/分钟/IP")
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

    config = uvicorn.Config(
        app,
        host=PROXY_HOST,
        port=PROXY_PORT,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    # 关键：禁用 signal handlers，防止 Windows 服务模式下误触发关闭
    server.install_signal_handlers = lambda: None
    server.run()
