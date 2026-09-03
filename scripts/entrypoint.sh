#!/bin/sh
set -eu

echo "[entrypoint] Starting HRMS production entrypoint..."

python - <<'PY'
import os
import time
import sys


# =============================================================================
# Environment helper
# =============================================================================

def env_value(name, default=None):
    """
    Return an environment variable only if it contains a non-empty value.
    This prevents values such as DB_PORT="" from breaking the application.
    """
    value = os.environ.get(name)

    if value is None:
        return default

    value = value.strip()

    if not value:
        return default

    return value


# =============================================================================
# Database engine
# =============================================================================

engine = env_value("DJANGO_DB_ENGINE", "postgres").lower()


# =============================================================================
# SQLite
# =============================================================================

if engine == "sqlite":
    print("[entrypoint] SQLite selected.")
    print("[entrypoint] Skipping PostgreSQL readiness check.")
    sys.exit(0)


# =============================================================================
# Validate database engine
# =============================================================================

if engine != "postgres":
    print(
        f"[entrypoint] ERROR: Unsupported DJANGO_DB_ENGINE='{engine}'.",
        file=sys.stderr,
    )

    print(
        "[entrypoint] Expected 'postgres' or 'sqlite'.",
        file=sys.stderr,
    )

    sys.exit(1)


# =============================================================================
# PostgreSQL
# =============================================================================

try:
    import psycopg2
except ImportError:
    print(
        "[entrypoint] ERROR: psycopg2 is not installed.",
        file=sys.stderr,
    )
    sys.exit(1)


# =============================================================================
# PostgreSQL connection
# =============================================================================
#
# Priority:
#
# 1. DATABASE_URL
# 2. DB_* variables
# 3. Railway PG* variables
# 4. Safe defaults
#
# Empty variables are ignored.
# =============================================================================

database_url = env_value("DATABASE_URL")


if database_url:

    connection_kwargs = {
        "dsn": database_url,
        "connect_timeout": 3,
    }

    connection_description = "DATABASE_URL"

else:

    host = env_value(
        "DB_HOST",
        env_value("PGHOST", "localhost"),
    )

    port = env_value(
        "DB_PORT",
        env_value("PGPORT", "5432"),
    )

    name = env_value(
        "DB_NAME",
        env_value("PGDATABASE", "hrms_db"),
    )

    user = env_value(
        "DB_USER",
        env_value("PGUSER", "hrms_user"),
    )

    password = env_value(
        "DB_PASSWORD",
        env_value("PGPASSWORD", ""),
    )

    try:
        port = int(port)
    except (TypeError, ValueError):
        print(
            f"[entrypoint] ERROR: Invalid PostgreSQL port: '{port}'",
            file=sys.stderr,
        )
        sys.exit(1)

    connection_kwargs = {
        "dbname": name,
        "user": user,
        "password": password,
        "host": host,
        "port": port,
        "connect_timeout": 3,
    }

    connection_description = f"{host}:{port}/{name}"


# =============================================================================
# Database wait configuration
# =============================================================================

try:
    wait_seconds = int(
        env_value("DB_WAIT_SECONDS", "120")
    )
except ValueError:
    wait_seconds = 120


deadline = time.time() + wait_seconds
last_error = None


# =============================================================================
# Wait for PostgreSQL
# =============================================================================

print(
    f"[entrypoint] Waiting for PostgreSQL ({connection_description})..."
)


while time.time() < deadline:

    try:

        conn = psycopg2.connect(
            **connection_kwargs
        )

        conn.close()

        print(
            "[entrypoint] Database is ready."
        )

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

    print(
        f"[entrypoint] Last error: {last_error}",
        file=sys.stderr,
    )

    sys.exit(1)


PY


# =============================================================================
# Django migrations
# =============================================================================

echo "[entrypoint] Running database migrations..."

python manage.py migrate --noinput


# =============================================================================
# Application configuration (permissions, roles, leave types, settings)
# Never runs seed_demo_data — that would wipe operational records.
# =============================================================================

echo "[entrypoint] Bootstrapping system configuration..."

python manage.py bootstrap_system


# =============================================================================
# Static files
# =============================================================================

echo "[entrypoint] Collecting static files..."

python manage.py collectstatic --noinput


# =============================================================================
# Start Gunicorn
# =============================================================================

echo "[entrypoint] Starting application: $*"

exec "$@"
