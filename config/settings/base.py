"""Base settings shared by dev and prod (agent.md §4: config/settings split).

Step 1 delivers the minimal bootable core; Celery, i18n catalogs, and the
integration-toggle validation check are layered on in Step 2.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------
# Env helpers
# --------------------------------------------------------------------------
def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env flag; missing/blank values fall back to `default`."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list | None = None) -> list:
    """Read a comma-separated env value into a list of stripped strings."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default if default is not None else []
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------
# Core Django
# --------------------------------------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-secret-key")
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # CarFlow apps (agent.md §4). More are added as each build step ships.
    "apps.core",
    "apps.organizations",
    "apps.branches",
    "apps.accounts",
    "apps.vehicles",
    "apps.inventory",
    "apps.suppliers",
    "apps.purchases",
    "apps.customers",
    "apps.sales",
    "apps.payments",
    "apps.expenses",
    "apps.accounting",
    "apps.audit",
    "apps.communications",
    "apps.documents",
    # Third-party (audit trail, agent.md §6/§10 Step 8).
    "simple_history",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # LocaleMiddleware sits after SessionMiddleware and before CommonMiddleware
    # so the session-stored language preference drives every request (§11.1).
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Tenant context comes from the authenticated user's company (§5).
    "apps.core.middleware.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Records the requesting user on simple-history rows (Step 8).
    "simple_history.middleware.HistoryRequestMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "carflow"),
        "USER": os.environ.get("DB_USER", "carflow"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "db"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Internal system: English, Dari (prs), Pashto (ps) — UI chrome only (§11).
# "prs" (ISO 639-3 for Dari) is the project-wide locale code.
LANGUAGES = [
    ("en", "English"),
    ("prs", "Dari"),
    ("ps", "Pashto"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom user model (must be set before the first migration of accounts).
AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"


# --------------------------------------------------------------------------
# Third-party integration toggles (agent.md §12)
# When a flag is False the credential variables may be blank and the app must
# still boot; the factory layer returns Null/Console adapters instead.
# --------------------------------------------------------------------------
META_ENABLED = env_bool("META_ENABLED", default=False)
META_APP_ID = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
META_WEBHOOK_VERIFY_TOKEN = os.environ.get("META_WEBHOOK_VERIFY_TOKEN", "")
META_WHATSAPP_PHONE_NUMBER_ID = os.environ.get("META_WHATSAPP_PHONE_NUMBER_ID", "")
META_MESSENGER_PAGE_ID = os.environ.get("META_MESSENGER_PAGE_ID", "")
META_INSTAGRAM_PAGE_ID = os.environ.get("META_INSTAGRAM_PAGE_ID", "")

TELEGRAM_ENABLED = env_bool("TELEGRAM_ENABLED", default=False)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

SMS_ENABLED = env_bool("SMS_ENABLED", default=False)
SMS_GATEWAY_URL = os.environ.get("SMS_GATEWAY_URL", "")
SMS_GATEWAY_API_KEY = os.environ.get("SMS_GATEWAY_API_KEY", "")

EMAIL_ENABLED = env_bool("EMAIL_ENABLED", default=False)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587") or 587)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "notifications@localhost")

S3_ENABLED = env_bool("S3_ENABLED", default=False)
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "")

# Redis serves as both the Django cache backend and the Celery broker (§2).
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# --------------------------------------------------------------------------
# Celery (worker + Beat) — broker and results on Redis (§2).
# --------------------------------------------------------------------------
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TIMEZONE = TIME_ZONE
# Phase 2 workflows (inventory aging, payment overdue, document expiry) will
# register their schedules here; the hook exists from Phase 1.
CELERY_BEAT_SCHEDULE = {}

# --------------------------------------------------------------------------
# File storage backend (§12.2): local `media/` volume by default, S3 when
# `S3_ENABLED` is on. This block is the ONLY place S3 is referenced — app
# code just uses `FileField` and never knows where bytes land.
# --------------------------------------------------------------------------
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
if S3_ENABLED:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "endpoint_url": S3_ENDPOINT_URL or None,
            "access_key": S3_ACCESS_KEY,
            "secret_key": S3_SECRET_KEY,
            "bucket_name": S3_BUCKET_NAME,
        },
    }
