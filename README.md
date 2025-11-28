1. uvicorn src.api_server:app --host 0.0.0.0 --port 8000
2. python -m src.main
3. docker build -t lazylemonkitty/proarb_build:latest .
4. docker push lazylemonkitty/proarb_build:latest
5. docker pull lazylemonkitty/proarb_build:latest