# 单容器运行（monitor + FastAPI 同时运行）

Build:
  docker build -t arb-engine:single .

Run（建议挂载 data 和 config）：
   docker run -d --name proarb --env-file .env -e CONFIG_PATH=/app/config.yaml -e EV_REFRESH_SECONDS=10 -p 8000:8000 -v $(pwd)/data:/app/data -v $(pwd)/config.yaml:/app/config.yaml:ro lazylemonkitty/proarb_build:latest

Check:
  curl http://127.0.0.1:8000/api/health
  curl http://127.0.0.1:8000/api/pm
  curl http://127.0.0.1:8000/api/db
  curl http://127.0.0.1:8000/api/ev

Logs:
  docker logs -f arb-engine
