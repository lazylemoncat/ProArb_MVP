1. .venv\Scripts\activate
2. uvicorn src.api_server:app --host 0.0.0.0 --port 8000
3. python -m src.main
4. docker build -t lazylemonkitty/proarb_build:latest .
5. docker push lazylemonkitty/proarb_build:latest
6. docker pull lazylemonkitty/proarb_build:latest
7. docker stop proarb
8. docker rm proarb
9. scp .env rex@104.248.192.200:~
10. scp config.yaml rex@104.248.192.200:~
11. scp trading_config.yaml rex@104.248.192.200:~
12. docker run -d --name proarb --env-file .env -e CONFIG_PATH=/app/config.yaml  -e TRADING_CONFIG_PATH=/app/trading_config.yaml -e EV_REFRESH_SECONDS=10 -p 8000:8000 -v $(pwd)/data:/app/data -v $(pwd)/config.yaml:/app/config.yaml:ro -v $(pwd)/trading_config.yaml:/app/trading_config.yaml:ro lazylemonkitty/proarb_build:latest
13. scp rex@104.248.192.200:data/positions.csv ./data/positions.csv
14. scp rex@104.248.192.200:data/results.csv ./data/results.csv
15. scp rex@104.248.192.200:data/raw_results.csv ./data/raw_results.csv
16. scp rex@104.248.192.200:data/proarb.log ./data/proarb.log 
17. docker logs -f -n 200 proarb
18. docker pull mysql:8.4.7