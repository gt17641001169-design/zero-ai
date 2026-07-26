#!/bin/bash
# ZeroAI Proxy 部署脚本（Ubuntu）
# 使用方式：bash start.sh [install|start|stop|restart|status|logs]

set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
SERVICE_NAME="zeroai-proxy"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] WARN:${NC} $1"; }
err()  { echo -e "${RED}[$(date +%H:%M:%S)] ERR:${NC} $1"; }

# 1. 安装
install_app() {
    log "安装 ZeroAI Proxy..."

    # 检查 .env
    if [ ! -f "$APP_DIR/.env" ]; then
        err ".env 文件不存在，请先复制 .env.example 并配置"
        echo "  cp .env.example .env"
        echo "  nano .env"
        exit 1
    fi

    # 检查 GLM_API_KEY
    if grep -q "your_glm_api_key_here" "$APP_DIR/.env"; then
        err ".env 中 GLM_API_KEY 未修改，请填入真实 Key"
        exit 1
    fi

    # 创建虚拟环境
    if [ ! -d "$VENV_DIR" ]; then
        log "创建虚拟环境..."
        python3 -m venv "$VENV_DIR"
    fi

    # 安装依赖（清华镜像）
    log "安装依赖（清华镜像）..."
    "$VENV_DIR/bin/pip" install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
    "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple

    # 安装 systemd 服务
    log "安装 systemd 服务..."
    cat > /tmp/$SERVICE_NAME.service << EOF
[Unit]
Description=ZeroAI Proxy - API Key Protection
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python $APP_DIR/main.py
Restart=on-failure
RestartSec=5
StandardOutput=append:$APP_DIR/logs/app.log
StandardError=append:$APP_DIR/logs/error.log

[Install]
WantedBy=multi-user.target
EOF

    mkdir -p "$APP_DIR/logs"
    sudo cp /tmp/$SERVICE_NAME.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable $SERVICE_NAME

    log "安装完成。下一步："
    echo "  bash start.sh start    # 启动"
    echo "  bash start.sh status   # 查看状态"
}

# 2. 启动
start_app() {
    log "启动 $SERVICE_NAME..."
    sudo systemctl start $SERVICE_NAME
    sleep 2
    status_app
}

# 3. 停止
stop_app() {
    log "停止 $SERVICE_NAME..."
    sudo systemctl stop $SERVICE_NAME
}

# 4. 重启
restart_app() {
    log "重启 $SERVICE_NAME..."
    sudo systemctl restart $SERVICE_NAME
    sleep 2
    status_app
}

# 5. 状态
status_app() {
    echo -e "${GREEN}=== 服务状态 ===${NC}"
    sudo systemctl status $SERVICE_NAME --no-pager -l | head -20
    echo ""
    echo -e "${GREEN}=== 健康检查 ===${NC}"
    if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
        curl -s http://localhost:8000/health | python3 -m json.tool
    else
        err "服务未响应，请检查日志：bash start.sh logs"
    fi
}

# 6. 日志
show_logs() {
    log "实时日志（Ctrl+C 退出）..."
    sudo journalctl -u $SERVICE_NAME -f
}

# 主入口
case "$1" in
    install)  install_app ;;
    start)    start_app ;;
    stop)     stop_app ;;
    restart)  restart_app ;;
    status)   status_app ;;
    logs)     show_logs ;;
    *)
        echo "用法: bash start.sh [install|start|stop|restart|status|logs]"
        echo ""
        echo "首次部署流程："
        echo "  1. cp .env.example .env && nano .env     # 配置"
        echo "  2. bash start.sh install                  # 安装"
        echo "  3. bash start.sh start                    # 启动"
        echo "  4. bash start.sh status                   # 查看状态"
        ;;
esac
