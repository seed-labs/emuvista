FROM python:3.12-slim

WORKDIR /app
COPY runner.py ./runner.py
COPY agent_worker.py ./agent_worker.py
COPY server.crt ./server.crt

CMD ["python", "-u", "/app/runner.py"]
