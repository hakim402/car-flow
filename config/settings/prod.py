"""Production settings (used by the base docker-compose.yml)."""
import os

from .base import *  # noqa: F401,F403

DEBUG = False

# HTTPS behind Nginx.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Secure cookies only work over HTTPS. They stay on by default (real
# deployments are TLS-terminated before traffic reaches this app), but a
# plain-HTTP deployment — e.g. the prod stack run locally — must set
# COOKIES_SECURE=False or every form POST fails with a CSRF 403.
COOKIES_SECURE = env_bool("COOKIES_SECURE", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = COOKIES_SECURE
CSRF_COOKIE_SECURE = COOKIES_SECURE
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Real SMTP only when EMAIL_ENABLED; otherwise keep the console backend so a
# disabled integration can never crash outbound flows (agent.md §12.2).
if EMAIL_ENABLED:  # noqa: F405
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Storage backend (local media vs S3) is selected in base.py on S3_ENABLED —
# that block is the ONLY place S3 is referenced (agent.md §12.2).

LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
}
