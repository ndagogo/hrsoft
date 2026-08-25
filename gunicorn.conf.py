"""Gunicorn configuration for production WSGI serving."""

import multiprocessing
import os


# =============================================================================
# NETWORK / RAILWAY PORT
# =============================================================================
#
# Railway provides the PORT environment variable dynamically.
#
# Example:
# PORT=8080
#
# Gunicorn must listen on the same port Railway assigns.
#
# GUNICORN_BIND can still be explicitly supplied if needed.
# =============================================================================

railway_port = os.environ.get("PORT", "8000")

bind = os.environ.get(
    "GUNICORN_BIND",
    f"0.0.0.0:{railway_port}",
)


# =============================================================================
# WORKERS
# =============================================================================
#
# Railway containers can have different CPU allocations.
# Avoid creating an excessive number of workers on small Railway instances.
#
# Default: 3 workers.
# =============================================================================

workers = int(
    os.environ.get(
        "GUNICORN_WORKERS",
        "3",
    )
)

threads = int(
    os.environ.get(
        "GUNICORN_THREADS",
        "2",
    )
)

worker_class = os.environ.get(
    "GUNICORN_WORKER_CLASS",
    "gthread",
)


# =============================================================================
# TIMEOUTS
# =============================================================================

timeout = int(
    os.environ.get(
        "GUNICORN_TIMEOUT",
        "60",
    )
)

graceful_timeout = int(
    os.environ.get(
        "GUNICORN_GRACEFUL_TIMEOUT",
        "30",
    )
)

keepalive = int(
    os.environ.get(
        "GUNICORN_KEEPALIVE",
        "5",
    )
)


# =============================================================================
# WORKER RECYCLING
# =============================================================================
#
# Helps protect against gradual memory growth in long-running processes.
# =============================================================================

max_requests = int(
    os.environ.get(
        "GUNICORN_MAX_REQUESTS",
        "1000",
    )
)

max_requests_jitter = int(
    os.environ.get(
        "GUNICORN_MAX_REQUESTS_JITTER",
        "100",
    )
)


# =============================================================================
# APPLICATION LOADING
# =============================================================================

preload_app = (
    os.environ.get(
        "GUNICORN_PRELOAD",
        "true",
    ).lower()
    in {"1", "true", "yes", "on"}
)


# =============================================================================
# LOGGING
# =============================================================================
#
# "-" sends logs to stdout/stderr, which is exactly what we want on Railway.
# Railway captures container stdout/stderr for its deployment logs.
# =============================================================================

accesslog = os.environ.get(
    "GUNICORN_ACCESS_LOG",
    "-",
)

errorlog = os.environ.get(
    "GUNICORN_ERROR_LOG",
    "-",
)

loglevel = os.environ.get(
    "GUNICORN_LOG_LEVEL",
    "info",
)

capture_output = True
enable_stdio_inheritance = True


# =============================================================================
# PROXY / FORWARDED HEADERS
# =============================================================================
#
# Railway sits in front of the application as a reverse proxy.
#
# Django's settings.py already handles:
#
#     SECURE_PROXY_SSL_HEADER
#     USE_X_FORWARDED_HOST
#
# Gunicorn is configured to trust forwarded requests.
# =============================================================================

forwarded_allow_ips = os.environ.get(
    "GUNICORN_FORWARDED_ALLOW_IPS",
    "*",
)
