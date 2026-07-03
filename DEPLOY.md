# 部署到你的 VPS / 云主机

把 FinanceAgent Web 控制台跑到你自己的服务器上。**推荐 Docker 方式**，最省心。

> 形态：Next.js 前端 (`web/`, 对外 8501) + FastAPI 数据后端 (`api/`, 仅内网 8000)，
> `docker compose up -d --build` 一条命令起两个服务。用途：**仅回测 / 分析**，不接交易接口。
> 旧版 Streamlit 控制台仍保留在 `app.py`（`streamlit run app.py` 可本地使用），但不再是部署形态。

---

## 方式 A：Docker（推荐）

服务器需已安装 Docker（[安装文档](https://docs.docker.com/engine/install/)）。

```bash
# 1. 把代码弄到服务器
git clone <你的仓库地址> FinanceAgent
cd FinanceAgent

# 2. 一键起服务
bash deploy/deploy.sh
```

脚本会构建镜像并后台启动容器。默认绑定到 `127.0.0.1:8501`（配合下面的 Nginx 反代，更安全）。

**想先快速验证 / 直接公网访问**：把 `docker-compose.yml` 里端口从
`"127.0.0.1:8501:8501"` 改成 `"8501:8501"`，再 `bash deploy/deploy.sh`，
然后浏览器打开 `http://<服务器IP>:8501`（记得在云厂商安全组放行 8501）。

常用命令：

```bash
docker compose logs -f      # 看日志
docker compose restart      # 重启
docker compose down         # 停止
docker compose up -d --build  # 改了代码后重新部署
```

---

## 方式 B：裸机 + systemd（不想用 Docker）

```bash
git clone <你的仓库地址> /opt/FinanceAgent
cd /opt/FinanceAgent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 注册为系统服务 (开机自启 + 崩溃重启)
sudo cp deploy/financeagent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now financeagent
journalctl -u financeagent -f     # 看日志
```

服务监听 `127.0.0.1:8501`，同样建议用 Nginx 反代对外。

---

## 配 Nginx 反向代理（绑域名 / 上 HTTPS）

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/financeagent
# 编辑文件, 把 server_name 改成你的域名或公网 IP
sudo ln -s /etc/nginx/sites-available/financeagent /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

> Streamlit 用 WebSocket，`nginx.conf` 里已带好 `Upgrade` 头，别删。

**免费 HTTPS**（有域名时）：

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## 安全建议（务必看）

公网暴露一个能跑代码的服务，最好做到：

1. **别直接裸暴露 8501**：用 Nginx 反代，只对外开 80/443。
2. **加访问口令**（Nginx Basic Auth）：
   ```bash
   sudo apt install apache2-utils
   sudo htpasswd -c /etc/nginx/.htpasswd youruser
   ```
   然后取消 `deploy/nginx.conf` 里 `auth_basic` 两行的注释，reload。
3. **防火墙**：`ufw allow 80,443/tcp` + `ufw enable`，关掉用不到的端口。
4. 本项目当前**不含任何交易/下单接口**，泄露风险有限；但若以后接实盘，
   API 密钥务必用环境变量 / secrets，绝不要写进代码或提交到 Git。

---

## 常见问题

- **页面打不开 / 转圈**：多半是 Nginx 少了 WebSocket 的 `Upgrade` 头，或安全组没放行端口。
- **拉不到行情**：服务器到 Yahoo Finance 的网络不通时会自动回退合成数据；
  控制台仍能跑，只是数据非真实。检查服务器出网或换数据源（A股可接 akshare）。
- **改了代码不生效**：Docker 下需 `docker compose up -d --build` 重建镜像。
