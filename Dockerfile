# 使用 Debian 系 Python 镜像
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 让 Python 能直接找到 src 下面的 utils / fetch_data / strategy 等包
    PYTHONPATH=/app/src

WORKDIR /app

# 1. 删掉默认 deb.debian.org 的 sources 文件
# 2. 写入阿里云镜像源
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf 'deb http://mirrors.aliyun.com/debian bookworm main contrib non-free non-free-firmware\n\
deb http://mirrors.aliyun.com/debian bookworm-updates main contrib non-free non-free-firmware\n\
deb http://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free non-free-firmware\n' > /etc/apt/sources.list

# 安装 nginx
RUN apt-get update && \
    apt-get install -y --no-install-recommends nginx && \
    rm -rf /var/lib/apt/lists/*

# 拷贝整个项目
COPY . /app

# 安装 Python 依赖：
# 1) FastAPI + Uvicorn
# 2) 根据 pyproject.toml 安装项目本身
RUN pip install --no-cache-dir "fastapi" "uvicorn[standard]" && \
    pip install --no-cache-dir .

# 使用自己的 nginx 配置
RUN rm -f /etc/nginx/sites-enabled/default || true
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# 同时运行：
# - 监控：python -m utils.main    （src/utils/main.py）
# - FastAPI：uvicorn utils.main:app
# - nginx：前台运行
CMD ["sh", "-c", "python -u -m src.main & uvicorn src.main:app --host 0.0.0.0 --port 8000 & nginx -g 'daemon off;'"]
