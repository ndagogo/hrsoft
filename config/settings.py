"""
Django settings for the HRMS (HR Management System) project.

Enterprise-grade HR platform with RBAC, attendance/biometric integration,
leave management and payroll.
"""

from pathlib import Path
import os
from django.core.exceptions import ImproperlyConfigured
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from a .env file in the project root, if present.
# In production, prefer setting real environment variables instead.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core / security
# ---------------------------------------------------------------------------
_INSECURE_SECRET_FALLBACK = "django-insecure-CHANGE-THIS-KEY-IN-PRODUCTION-xk29s8df72hsdq"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _INSECURE_SECRET_FALLBACK)

DEBUG = _env_bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1")

CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

if not DEBUG:
    if not SECRET_KEY or SECRET_KEY == _INSECURE_SECRET_FALLBACK or SECRET_KEY.startswith("django-insecure"):
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set to a strong random value when DJANGO_DEBUG=False."
        )
    if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["*"]:
        raise ImproperlyConfigured(
            "DJANGO_ALLOWED_HOSTS must list your production domain(s) when DJANGO_DEBUG=False."
        )
    if os.environ.get("DJANGO_DB_ENGINE", "postgres") == "sqlite":
        raise ImproperlyConfigured(
            "SQLite is not supported for production. Set DJANGO_DB_ENGINE=postgres."
        )

# HSTS preload is opt-in (irreversible once submitted). Enable via env when ready.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    # Third-party
    "crispy_forms",
    "crispy_bootstrap5",

    # Local apps
    "apps.core",
    "apps.accounts",
    "apps.rbac",
    "apps.organization",
    "apps.employees",
    "apps.attendance",
    "apps.leave",
    "apps.payroll",
    "apps.recruitment",
    "apps.performance",
    "apps.training",
    "apps.assets",
    "apps.documents",
    "apps.visitors",
    "apps.notifications",
    "apps.announcements",
    "apps.system_settings",
    "apps.reports",
    "apps.selfservice",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.LoginRequiredMiddleware",
    "apps.core.middleware.ForcePasswordChangeMiddleware",
    "apps.core.middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site_branding",
                "apps.core.context_processors.nav_permissions",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# PostgreSQL by default (production-grade). Override via environment
# variables. Falls back gracefully to sqlite only if explicitly requested
# with DJANGO_DB_ENGINE=sqlite (handy for a quick local trial run).
if os.environ.get("DJANGO_DB_ENGINE", "postgres") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "hrms_db"),
            "USER": os.environ.get("DB_USER", "hrms_user"),
            "PASSWORD": os.environ.get("DB_PASSWORD", "hrms_password"),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
            "OPTIONS": {
                "connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
            },
        }
    }

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:router"
LOGOUT_REDIRECT_URL = "accounts:login"

# URLs that don't require authentication (used by LoginRequiredMiddleware)
PUBLIC_URLS = [
    "/accounts/login/",
    "/accounts/logout/",
    "/accounts/mfa/verify/",
    "/accounts/password-reset/",
    "/accounts/password-reset/done/",
    "/accounts/reset/",
    "/api/biometric/webhook/",
    "/api/v1/biometric/",
    "/api/v1/device/",
    "/admin/login/",
    "/recruitment/careers/",
    "/healthz/",
]

# Still require login even if nested under a PUBLIC_URLS prefix
PROTECTED_URL_PREFIXES = [
    "/api/v1/device/manage/",
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Africa/Lagos")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static / media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Manifest-based storage (content-hashed filenames + far-future cache headers)
# only makes sense once `collectstatic` has actually been run, which is a
# production deployment step. In DEBUG, fall back to plain storage so
# `runserver` works immediately without that extra step.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if not DEBUG
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media")))

# Gunicorn/Railway have no nginx in front of /media/. Serve uploads from Django
# unless explicitly disabled (DJANGO_SERVE_MEDIA=False when nginx or S3 handles files).
SERVE_MEDIA = _env_bool("DJANGO_SERVE_MEDIA", default=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Large video course uploads stream to disk above FILE_UPLOAD_MAX_MEMORY_SIZE.
# DATA_UPLOAD_MAX_MEMORY_SIZE must cover the whole multipart body (default raised for L&D videos).
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get("FILE_UPLOAD_MAX_MEMORY_SIZE", 10 * 1024 * 1024))
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get("DATA_UPLOAD_MAX_MEMORY_SIZE", 512 * 1024 * 1024))
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(os.environ.get("DATA_UPLOAD_MAX_NUMBER_FIELDS", 2000))

# ---------------------------------------------------------------------------
# Crispy forms
# ---------------------------------------------------------------------------
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# ---------------------------------------------------------------------------
# Sessions / security hardening
# ---------------------------------------------------------------------------
# Idle timeout: logged-in users are signed out after this many seconds without
# browser activity. SESSION_SAVE_EVERY_REQUEST refreshes the expiry on each
# request so active users are not logged out mid-session.
IDLE_SESSION_TIMEOUT_SECONDS = int(os.environ.get("IDLE_SESSION_TIMEOUT_SECONDS", 120))
SESSION_COOKIE_AGE = IDLE_SESSION_TIMEOUT_SECONDS
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # JS (AJAX forms) needs to read the CSRF cookie
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Trust X-Forwarded-Proto / Host when behind nginx or a load balancer.
if _env_bool("DJANGO_BEHIND_PROXY", default=not DEBUG):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

if not DEBUG:
    # Secure cookies / HSTS only when HTTPS is actually terminated in front of the app.
    # For plain-HTTP staging (Docker on :80), set DJANGO_SECURE_SSL_REDIRECT=False.
    SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    _secure_cookies = _env_bool("DJANGO_SECURE_COOKIES", default=SECURE_SSL_REDIRECT)
    SESSION_COOKIE_SECURE = _secure_cookies
    CSRF_COOKIE_SECURE = _secure_cookies
    SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]
    if SECURE_SSL_REDIRECT:
        SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
        SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
            "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
        )
        SECURE_HSTS_PRELOAD = _env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)


# ---------------------------------------------------------------------------
# HRMS / Biometric device settings
# ---------------------------------------------------------------------------
BIOMETRIC_SETTINGS = {
    "PULL_POLL_INTERVAL_SECONDS": int(os.environ.get("BIOMETRIC_POLL_INTERVAL", 60)),
    "WEBHOOK_SHARED_SECRET": os.environ.get("BIOMETRIC_WEBHOOK_SECRET", "change-me-webhook-secret"),
    "ISAPI_TIMEOUT_SECONDS": 8,
    "ZK_TIMEOUT_SECONDS": int(os.environ.get("ZK_TIMEOUT_SECONDS", 10)),
    # Skip ICMP ping before TCP connect (ping is often blocked; TCP 4370 may still work)
    "ZK_OMIT_PING": os.environ.get("ZK_OMIT_PING", "True").strip().lower() in {"1", "true", "yes", "on"},
    "ZK_DEFAULT_IP": os.environ.get("ZK_DEFAULT_IP", "192.168.1.201"),
    "ZK_DEFAULT_PORT": int(os.environ.get("ZK_DEFAULT_PORT", 4370)),
    "LATE_GRACE_MINUTES": 10,
    "DEFAULT_WORKDAY_START": "09:00",
    "DEFAULT_WORKDAY_END": "17:00",
}

# Company-wide defaults shown across dashboards / payroll calculations
COMPANY_NAME = os.environ.get("COMPANY_NAME", "Northbridge Industries")
COMPANY_CURRENCY = os.environ.get("COMPANY_CURRENCY", "NGN")
COMPANY_CURRENCY_SYMBOL = os.environ.get("COMPANY_CURRENCY_SYMBOL", "₦")

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
# DEBUG: mailbox backend writes messages to disk for local testing.
# Production: configure SMTP via EMAIL_* env vars (recommended).
_DEFAULT_EMAIL_BACKEND = (
    "apps.core.mail.DevMailboxEmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", _DEFAULT_EMAIL_BACKEND)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@hrms.local")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
EMAIL_SUBJECT_PREFIX = os.environ.get("EMAIL_SUBJECT_PREFIX", "[HRMS] ")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = _env_bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "20"))

ADMINS = [
    tuple(item.split(":", 1))
    for item in _env_list("DJANGO_ADMINS")
    if ":" in item
]
MANAGERS = ADMINS

SMS_API_URL = os.environ.get("SMS_API_URL", "")
WHATSAPP_API_URL = os.environ.get("WHATSAPP_API_URL", "")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO" if not DEBUG else "DEBUG")
LOG_DIR = BASE_DIR / "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {process:d} {thread:d}: {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "hrms.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "verbose",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "errors.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "verbose",
            "level": "ERROR",
        },
    },
    "root": {
        "handlers": ["console", "file", "error_file"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file", "error_file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console", "file", "error_file"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps.attendance.biometrics": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "gunicorn.error": {
            "handlers": ["console", "file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "gunicorn.access": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

