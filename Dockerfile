# Dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 让 Python 能直接找到 src 下面的 utils / fetch_data / strategy 等包
    PYTHONPATH=/app/src

WORKDIR /app

# 安装系统依赖（包括 nginx）
RUN apt-get update && \
    apt-get install -y --no-install-recommends nginx && \
    rm -rf /var/lib/apt/lists/*

# 把所有代码拷进容器
COPY . /app

# 安装依赖：
# 1) FastAPI / uvicorn（如果 pyproject 里已经有，也只是 noop）
# 2) 项目本身（根据 pyproject.toml 自动装依赖）
RUN pip install --no-cache-dir "fastapi" "uvicorn[standard]" && \
    pip install --no-cache-dir .

# 替换 nginx 默认站点配置
RUN rm -f /etc/nginx/sites-enabled/default || true
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# 同时启动：
# - 监控：python -m utils.main
# - FastAPI：uvicorn utils.main:app
# - nginx：前台运行
CMD ["sh", "-c", "python -u -m utils.main & uvicorn utils.main:app --host 0.0.0.0 --port 8000 & nginx -g 'daemon off;'"]
