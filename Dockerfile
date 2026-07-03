# FinanceAgent Web 控制台镜像
FROM python:3.11-slim

WORKDIR /app

# 先装依赖 (利用缓存层)
# PIP_INDEX_URL 可通过 build-arg 覆盖; 国内服务器建议用镜像源, 例如
#   https://mirrors.cloud.tencent.com/pypi/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码
COPY . .

# 缓存/报告目录
RUN mkdir -p data reports

EXPOSE 8501

# 健康检查: Streamlit 自带 /_stcore/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
