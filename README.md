1. uvicorn src.api_server:app --host 0.0.0.0 --port 8000
2. python -m src.main
3. docker build -t lazylemonkitty/proarb_build:latest .
4. docker push lazylemonkitty/proarb_build:latest
5. docker pull lazylemonkitty/proarb_build:latest
6. docker stop proarb
7. docker rm proarb
8. scp .env rex@104.248.192.200:~
9. scp config.yaml rex@104.248.192.200:~
10. scp trading_config.yaml rex@104.248.192.200:~
11. docker run -d --name proarb --env-file .env -e CONFIG_PATH=/app/config.yaml  -e TRADING_CONFIG_PATH=/app/trading_config.yaml -e EV_REFRESH_SECONDS=10 -p 8000:8000 -v $(pwd)/data:/app/data -v $(pwd)/config.yaml:/app/config.yaml:ro -v $(pwd)/trading_config.yaml:/app/trading_config.yaml:ro lazylemonkitty/proarb_build:latest