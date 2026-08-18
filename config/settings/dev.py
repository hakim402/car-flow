"""Local development settings (used by docker-compose.override.yml)."""
from .base import *  # noqa: F401,F403

DEBUG = True

# Local dev is served directly by Django (no Nginx), so accept container host.
ALLOWED_HOSTS = ["*"]

# Emails print to the container log instead of requiring SMTP in dev.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Run Celery tasks inline in dev so webhook processing works even without a
# worker attached; prod keeps real workers (base setting stays False).
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
