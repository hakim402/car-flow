"""Test settings for the mandatory test gates (agent.md §10 Step 12).

The suite runs with zero external services: SQLite instead of PostgreSQL,
LocMem cache instead of Redis, eager Celery. Every integration toggle keeps
its base default — all ``*_ENABLED=False`` with empty credentials — which is
exactly the "integrations-off boot" gate the plan requires.
"""
from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# No Redis dependency in the suite.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}

# Webhook tasks (and any future Celery work) run inline during tests.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Fast password hashing for auth-heavy tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
