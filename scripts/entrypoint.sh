#!/bin/sh
set -eu

echo "[entrypoint] Starting HRMS production entrypoint..."

python - <<'PY'
import os
import time
import sys

engine = os.environ.get("DJANGO_DB_ENGINE", "postgres").strip().lower()

# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------
if engine == "sqlite":
    print("[entrypoint] SQLite selected. Skipping PostgreSQL readiness check.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
if engine != "postgres":
    print(
        f"[entrypoint] ERROR: Unsupported DJANGO_DB_ENGINE='{engine}'. "
        "Expected 'postgres' or 'sqlite'.",
        file=sys.stderr,
    )
    sys.exit(1)

import psycopg2

# ---------------------------------------------------------------------------
# Prefer DATABASE_URL.
# Railway PostgreSQL exposes DATABASE_URL automatically.
# ---------------------------------------------------------------------------
database_url = os.environ.get("DATABASE_URL", "").strip()

# ---------------------------------------------------------------------------
# Otherwise use PostgreSQL native variables or existing DB_* variables.
# This keeps the application compatible with Railway, VPS and Docker Compose.
# ---------------------------------------------------------------------------
if database_url:
    connection_kwargs = {
        "dsn": database_url,
        "connect_timeout": 3,
    }
    connection_description = "DATABASE_URL"

else:
    host = os.environ.get(
        "DB_HOST",
        os.environ.get("PGHOST", "localhost"),
    )

    port = os.environ.get(
        "DB_PORT",
        os.environ.get("PGPORT", "5432"),
    )

    name = os.environ.get(
        "DB_NAME",
        os.environ.get("PGDATABASE", "hrms_db"),
    )

    user = os.environ.get(
        "DB_USER",
        os.environ.get("PGUSER", "hrms_user"),
    )

    password = os.environ.get(
        "DB_PASSWORD",
        os.environ.get("PGPASSWORD", ""),
    )

    connection_kwargs = {
        "dbname": name,
        "user": user,
        "password": password,
        "host": host,
        "port": int(port),
        "connect_timeout": 3,
    }

    connection_description = f"{host}:{port}/{name}"


# ---------------------------------------------------------------------------
# Wait for database
# ---------------------------------------------------------------------------
wait_seconds = int(os.environ.get("DB_WAIT_SECONDS", "120"))
deadline = time.time() + wait_seconds
last_error = None

print(
    f"[entrypoint] Waiting for PostgreSQL ({connection_description})..."
)

while time.time() < deadline:
    try:
        conn = psycopg2.connect(**connection_kwargs)
        conn.close()

        print("[entrypoint] Database is ready.")
        break

    except Exception as exc:
        last_error = exc
        print(
            f"[entrypoint] Database not ready: {exc}",
            file=sys.stderr,
        )
        time.sleep(2)

else:
    print(
        f"[entrypoint] ERROR: Database was not ready after "
        f"{wait_seconds} seconds.",
        file=sys.stderr,
    )
    print(f"[entrypoint] Last error: {last_error}", file=sys.stderr)
    sys.exit(1)

PY


# =============================================================================
# Django migrations
# =============================================================================

echo "[entrypoint] Running database migrations..."

python manage.py migrate --noinput


# =============================================================================
# Static files
# =============================================================================

echo "[entrypoint] Collecting static files..."

python manage.py collectstatic --noinput


# =============================================================================
# Start application
# =============================================================================

echo "[entrypoint] Starting application: $*"

exec "$@"
