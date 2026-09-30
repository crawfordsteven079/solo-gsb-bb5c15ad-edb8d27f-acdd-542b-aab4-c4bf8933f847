#!/bin/sh
# 等待 PostgreSQL 就绪后建表，再启动 API。
set -e

echo "[entrypoint] waiting for database..."
python - <<'PY'
import os
import time

import psycopg2

# psycopg2.connect 接受标准 libpq URI；去掉 SQLAlchemy 方言前缀与查询参数
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
url = url.split("?", 1)[0]
deadline = time.time() + 60
while True:
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        conn.close()
        print("[entrypoint] database is ready")
        break
    except Exception as exc:  # noqa: BLE001
        if time.time() > deadline:
            raise SystemExit(f"[entrypoint] database not ready in time: {exc}")
        time.sleep(1)
PY

echo "[entrypoint] initializing schema..."
python -c "from app.database import init_db; init_db()"

echo "[entrypoint] starting API..."
exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" --log-level "${LOG_LEVEL:-info}"
