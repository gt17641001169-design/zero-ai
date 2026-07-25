# ZeroAI Proxy

> 保护 ZeroAI 客户端 API Key 的代理服务

## 工作原理

```
ZeroAI 客户端  ──(Token 鉴权)──>  ZeroAI Proxy  ──(真实 Key)──>  智谱 GLM API
   (无 API Key)                    (服务器端 .env)                 (上游)
```

- 客户端只持有 **访问 Token**（不是 API Key）
- 真实 GLM API Key 只存在于服务器 `.env` 文件
- 即使客户端被反编译 / 抓包，也无法获取真实 Key

## 特性

- **API Key 保护**：真实 Key 只在服务器端
- **Token 鉴权**：客户端用独立 Token 访问
- **限流防护**：每 IP 滑动窗口限流（默认 30 次/分钟）
- **模型白名单**：防止客户端调用昂贵模型
- **流式透传**：完整支持 SSE 流式响应
- **OpenAI 兼容**：客户端无需改造 SDK
- **日志审计**：所有请求记录 IP / Token / 模型 / 状态

## 文件结构

```
zeroai-proxy/
├── main.py              # 主程序（FastAPI）
├── .env.example         # 配置模板
├── .env                 # 实际配置（不进 Git）
├── requirements.txt     # 依赖
├── Dockerfile           # 容器镜像
├── docker-compose.yml   # 容器编排
├── start.sh             # 部署脚本（systemd）
└── README.md
```

## 部署方式

### 方式一：systemd（推荐，轻量）

```bash
# 1. 拷贝项目到服务器
scp -r zeroai-proxy/ guantong@192.168.10.22:/srv/projects/

# 2. SSH 登录服务器
ssh guantong@192.168.10.22

# 3. 进入目录
cd /srv/projects/zeroai-proxy

# 4. 配置 .env
cp .env.example .env
nano .env
#   - 填入 UPSTREAM_API_KEY（智谱真实 Key）
#   - 修改 CLIENT_TOKENS（生成：python3 -c "import secrets; print(secrets.token_urlsafe(32))"）

# 5. 安装 + 启动
bash start.sh install
bash start.sh start

# 6. 验证
bash start.sh status
curl http://localhost:8000/health
```

### 方式二：Docker（隔离）

```bash
cd /srv/projects/zeroai-proxy
cp .env.example .env
nano .env

docker compose up -d --build
docker compose logs -f
```

## 防火墙配置

```bash
# 开放代理端口（仅内网访问，不要开放公网）
sudo ufw allow from 192.168.10.0/24 to any port 8000 proto tcp
sudo ufw reload
```

## 客户端配置

ZeroAI 客户端（`~/.zeroai/config.json`）添加：

```json
{
  "proxy": {
    "enabled": true,
    "base_url": "http://192.168.10.22:8000/v1",
    "token": "你的_CLIENT_TOKENS_中的值"
  }
}
```

或环境变量：

```bash
export ZEROAI_PROXY_URL=http://192.168.10.22:8000/v1
export ZEROAI_PROXY_TOKEN=你的_Token
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查（无需鉴权） |
| `/v1/chat/completions` | POST | OpenAI 兼容聊天端点 |
| `/v1/models` | GET | 模型列表 |
| `/docs` | GET | Swagger 文档 |

## 测试代理

```bash
# 健康检查
curl http://localhost:8000/health

# 非流式
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer 你的_Token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4.7-flash",
    "messages": [{"role": "user", "content": "你好"}]
  }'

# 流式
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer 你的_Token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4.7-flash",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

## 安全建议

1. **不要开放公网**：代理端口仅对内网开放
2. **强 Token**：`CLIENT_TOKENS` 至少 32 字节随机
3. **定期轮换**：每 3 个月更换 Token
4. **日志监控**：`bash start.sh logs` 监控异常请求
5. **HTTPS**：如需公网访问，前置 Nginx + Let's Encrypt

## 常见问题

### Q: 启动后报 "UPSTREAM_API_KEY 未配置"？

A: `.env` 文件未创建或 `UPSTREAM_API_KEY` 仍为 `your_glm_api_key_here`，请填入真实 Key。

### Q: 客户端报 401？

A: `Authorization: Bearer <Token>` 中的 Token 与 `.env` 的 `CLIENT_TOKENS` 不匹配。

### Q: 客户端报 429？

A: 触发限流，调高 `.env` 的 `RATE_LIMIT_PER_MIN`，重启服务。

### Q: 客户端报 403 "Model not allowed"？

A: 模型不在白名单，将模型名加入 `.env` 的 `ALLOWED_MODELS`，重启服务。

## 许可证

专有软件，仅 ZeroAI 项目使用。
