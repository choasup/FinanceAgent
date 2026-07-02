#!/usr/bin/env bash
# FinanceAgent 一键安装 (从 tar 包部署, 无需 GitHub)。
# 在解压后的项目根目录执行:  bash deploy/quickstart.sh
# 完成后浏览器打开:  http://<服务器IP>:8501
set -euo pipefail

cd "$(dirname "$0")/.."
echo "==> 项目目录: $(pwd)"

# 1. Docker (已装则跳过)
if ! command -v docker >/dev/null 2>&1; then
  echo "==> 安装 Docker ..."
  curl -fsSL https://get.docker.com | sh
fi

# 2. 对公网开放 8501 (快速验证配置; 之后建议按 DEPLOY.md 换 Nginx 反代)
sed -i 's/127.0.0.1:8501:8501/8501:8501/' docker-compose.yml || true

# 3. 构建并启动
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
echo "==> 构建镜像并启动 (首次约 2-5 分钟) ..."
$COMPOSE up -d --build

# 4. 系统防火墙放行 (ufw / firewalld 自适应; 都没有则跳过)
sudo ufw allow 8501/tcp 2>/dev/null \
  || (sudo firewall-cmd --add-port=8501/tcp --permanent && sudo firewall-cmd --reload) 2>/dev/null \
  || true

# 5. 健康检查
echo "==> 等待服务就绪 ..."
for i in $(seq 1 15); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8501/_stcore/health || true)
  [ "$code" = "200" ] && break
  sleep 2
done

echo
if [ "${code:-}" = "200" ]; then
  ip=$(curl -s --max-time 3 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
  echo "✅ 部署成功!  浏览器打开:  http://${ip}:8501"
  echo "   (打不开的话: 云厂商控制台安全组放行 TCP:8501)"
else
  echo "⚠️ 服务未就绪, 查看日志:  $COMPOSE logs --tail 50"
fi