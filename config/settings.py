"""
Django settings for the HRMS (HR Management System) project.

Enterprise-grade HR platform with RBAC, attendance/biometric integration,
leave management and payroll.
"""

from pathlib import Path
import os
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from a .env file in the project root, if present.
# In production, prefer setting real environment variables instead.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Core / security
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-CHANGE-THIS-KEY-IN-PRODUCTION-xk29s8df72hsdq",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

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
            "CONN_MAX_AGE": 60,
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
    "/admin/login/",
    "/recruitment/careers/",
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
STATIC_URL = "static/"
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
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Crispy forms
# ---------------------------------------------------------------------------
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# ---------------------------------------------------------------------------
# Sessions / security hardening
# ---------------------------------------------------------------------------
# Idle timeout: logged-in users are signed out after this many seconds without
# browser activity (mouse/keyboard/touch/scroll). Also applied server-side via
# SESSION_COOKIE_AGE + SESSION_SAVE_EVERY_REQUEST so idle tabs expire even if
# JavaScript is disabled.
IDLE_SESSION_TIMEOUT_SECONDS = int(os.environ.get("IDLE_SESSION_TIMEOUT_SECONDS", 120))
SESSION_COOKIE_AGE = IDLE_SESSION_TIMEOUT_SECONDS
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
CSRF_COOKIE_HTTPONLY = False
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = False  # set True behind HTTPS-terminating proxy

# ---------------------------------------------------------------------------
# HRMS / Biometric device settings
# ---------------------------------------------------------------------------
# Primary site device (from Ethernet screen): ZKTeco at 192.168.1.201,
# TCP COMM. Port 4370, DHCP Off. HikVision ISAPI (HTTP :80) remains supported
# when brand=hikvision.
BIOMETRIC_SETTINGS = {
    "PULL_POLL_INTERVAL_SECONDS": int(os.environ.get("BIOMETRIC_POLL_INTERVAL", 60)),
    "WEBHOOK_SHARED_SECRET": os.environ.get("BIOMETRIC_WEBHOOK_SECRET", "change-me-webhook-secret"),
    "ISAPI_TIMEOUT_SECONDS": 8,
    "ZK_TIMEOUT_SECONDS": int(os.environ.get("ZK_TIMEOUT_SECONDS", 10)),
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

# Email backend for password reset
# In DEBUG, use the mailbox backend so reset links are written to disk and
# shown on the "email sent" page for local testing.
_DEFAULT_EMAIL_BACKEND = (
    "apps.core.mail.DevMailboxEmailBackend"
    if DEBUG
    else "django.core.mail.backends.console.EmailBackend"
)
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", _DEFAULT_EMAIL_BACKEND)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@hrms.local")
EMAIL_SUBJECT_PREFIX = os.environ.get("EMAIL_SUBJECT_PREFIX", "[HRMS] ")
SMS_API_URL = os.environ.get("SMS_API_URL", "")
WHATSAPP_API_URL = os.environ.get("WHATSAPP_API_URL", "")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "hrms.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apps.attendance.biometrics": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}

os.makedirs(BASE_DIR / "logs", exist_ok=True)
