#!/usr/bin/env bash
# FinanceAgent 一键部署 (Docker)。在你的服务器上 clone 仓库后执行本脚本。
#
#   git clone <你的仓库地址> FinanceAgent
#   cd FinanceAgent
#   bash deploy/deploy.sh
#
# 之后访问 http://<服务器IP>:8501 (若用 Nginx 反代见 deploy/nginx.conf)。
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 docker。请先安装: https://docs.docker.com/engine/install/"
  exit 1
fi

# 兼容 docker compose (v2) 与 docker-compose (v1)
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

echo "==> 构建镜像并启动容器 ..."
$COMPOSE up -d --build

echo "==> 等待健康检查 ..."
sleep 8
$COMPOSE ps

echo
echo "✅ 部署完成。"
echo "   - compose 默认绑定到 127.0.0.1:8501 (配合 Nginx 反代, 见 deploy/nginx.conf)"
echo "   - 想直接公网访问: 把 docker-compose.yml 端口改成 \"8501:8501\" 后重新 up"
echo "   - 查看日志: $COMPOSE logs -f"
echo "   - 停止:     $COMPOSE down"
