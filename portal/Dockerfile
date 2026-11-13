# 南海数港客户门户 — Dockerfile（Python 标准库，零外部依赖）
FROM python:3.12-slim
WORKDIR /app
COPY server.py .
COPY static ./static
# 门户数据（SQLite）存在 /data，挂 volume 持久化
VOLUME ["/data"]
ENV PORT=8080 DB_PATH=/data/portal.db
EXPOSE 8080
CMD ["python3", "server.py"]
