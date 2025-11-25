# syntax=docker/dockerfile:1
# 固定到 Debian 12(bookworm)，避免 python:3.12-slim 跟随 Debian testing(trixie) 导致 apt 源不稳定
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    EV_REFRESH_SECONDS=10 \
    LOG_LEVEL=INFO

WORKDIR /app

# ====== apt 换源（阿里云）======
# 说明：Debian 12 默认使用 /etc/apt/sources.list.d/debian.sources（不是 sources.list）
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf 'deb https://mirrors.aliyun.com/debian bookworm main contrib non-free non-free-firmware\n\
deb https://mirrors.aliyun.com/debian bookworm-updates main contrib non-free non-free-firmware\n\
deb https://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free non-free-firmware\n' > /etc/apt/sources.list

# 最小系统依赖：ca-certificates（HTTPS）、（可选）tzdata
# 注：不再通过 apt 安装 supervisor/curl，避免 apt 拉包失败；supervisor 用 pip 装。
RUN apt-get -o Acquire::Retries=5 update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# ====== pip 换源（阿里云 PyPI）======
# 如你不想换源，删掉下面两行即可。
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

# Install Python deps from pyproject.toml（不依赖 build backend）
COPY pyproject.toml /app/pyproject.toml
RUN python - <<'PY'
import subprocess, sys
import tomllib
with open('pyproject.toml','rb') as f:
    data = tomllib.load(f)
deps = list(data.get('project', {}).get('dependencies', []))
extra = ['uvicorn[standard]', 'fastapi', 'python-dotenv', 'certifi', 'supervisor']
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '--upgrade', 'pip'])
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *deps, *extra])
PY

# App code + default config（线上建议 bind-mount）
COPY src /app/src
COPY config.yaml /app/config.yaml
RUN mkdir -p /app/data

# Supervisor config（单容器跑 monitor + api）
COPY supervisord.conf /etc/supervisord.conf

EXPOSE 8000

# 不依赖 curl 的健康检查（用 Python 标准库请求）
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python - <<'PY'\n\
import urllib.request\n\
import sys\n\
try:\n\
    urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()\n\
except Exception:\n\
    sys.exit(1)\n\
PY

# 用 pip 安装的 supervisor 启动（前台）
CMD ["python", "-m", "supervisor.supervisord", "-n", "-c", "/etc/supervisord.conf"]
