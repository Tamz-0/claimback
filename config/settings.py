"""
Django settings for the Campus Lost & Found platform.

All secrets and environment-specific values come from environment variables
(loaded from a `.env` file in the project root). See `.env.example`.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    # Project apps (one per functional module in the spec)
    "apps.accounts",   # users and roles
    "apps.audit",      # AuditEntry + notifications
    "apps.catalog",    # M2 category & location taxonomy
    "apps.items",      # M1 item reporting
    "apps.vault",      # M4 private details & verification
    "apps.matching",   # M3 matching engine
    "apps.claims",     # M5 claim workflow
    "apps.custody",    # M6 custody & handover, M7 disposal
    "apps.board",      # M8 public board & search
    "apps.dashboard",  # admin dashboard, reports
    "apps.api",        # REST API
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
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.roles",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database -------------------------------------------------------------
# PostgreSQL is required (full-text search + pg_trgm are used for matching).
# Put your Supabase "Session pooler" connection string in DATABASE_URL.
DATABASES = {
    "default": dj_database_url.config(
        default="postgresql://lf:lf@localhost:5432/lostfound",
        conn_max_age=60,
        ssl_require=env_bool("DATABASE_SSL", False),
    )
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "board:list"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Email (console in development: emails are printed in the terminal) ---
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "lostandfound@campus.local")

# --- Cache (public board is cached) ---------------------------------------
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
BOARD_CACHE_SECONDS = int(os.environ.get("BOARD_CACHE_SECONDS", "60"))

# --- REST framework -------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# --- Encryption of private identifying details ----------------------------
# A Fernet key (generate with the command in README). If empty, a key is
# derived from SECRET_KEY so development works out of the box.
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "")

# --- Business rules (all configurable) ------------------------------------
LOSTFOUND = {
    # Verification challenge
    "CHALLENGE_QUESTIONS": 3,          # questions drawn per claim
    "CHALLENGE_MAX_ATTEMPTS": 2,       # attempts before the claim is locked
    "CHALLENGE_PASS_SCORE": 0.66,      # >= this passes automatically
    "CHALLENGE_REVIEW_SCORE": 0.45,    # between this and pass -> security review
    "MIN_PRIVATE_DETAILS": 2,          # found-item reporter must give at least this many
    # Matching
    "MATCH_THRESHOLD": 0.40,           # minimum score to store a suggestion
    "MATCH_MAX_PER_ITEM": 10,
    "MATCH_WINDOW_DAYS": 60,           # found item must be within this many days of the loss
    # Handover
    "OTP_TTL_MINUTES": 60 * 24,
    "OTP_MAX_ATTEMPTS": 5,
    # Ageing: warn this many days before the category retention period ends
    "AGEING_WARNING_DAYS": 7,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
