#!/bin/sh
set -eu

echo "[entrypoint] Waiting for database..."
python - <<'PY'
import os
import time
import sys

engine = os.environ.get("DJANGO_DB_ENGINE", "postgres")
if engine == "sqlite":
    sys.exit(0)

import psycopg2

host = os.environ.get("DB_HOST", "localhost")
port = int(os.environ.get("DB_PORT", "5432"))
name = os.environ.get("DB_NAME", "hrms_db")
user = os.environ.get("DB_USER", "hrms_user")
password = os.environ.get("DB_PASSWORD", "")

deadline = time.time() + int(os.environ.get("DB_WAIT_SECONDS", "60"))
last_error = None
while time.time() < deadline:
    try:
        conn = psycopg2.connect(
            dbname=name,
            user=user,
            password=password,
            host=host,
            port=port,
            connect_timeout=3,
        )
        conn.close()
        print("[entrypoint] Database is ready.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        last_error = exc
        time.sleep(2)

print(f"[entrypoint] Database not ready: {last_error}", file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] Running migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

echo "[entrypoint] Starting: $*"
exec "$@"
