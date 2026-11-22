FROM python:3.12-slim

WORKDIR /app
COPY static ./static
COPY server.py ./server.py
COPY server.crt ./server.crt

EXPOSE 8765
CMD ["python", "/app/server.py"]
