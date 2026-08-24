"""PostgreSQL-backed settings for integrity/concurrency tests.

The default suite (`config.settings.test`) runs on SQLite for speed and
isolation; the concurrency semantics that back the Phase-1 integrity
constraints (README §26/§28) require a real PostgreSQL transaction engine.
Run inside Docker:

    docker compose run --rm web pytest --ds=config.settings.test_postgres
"""
import os

from .test import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("TEST_DB_NAME", "carflow_test"),
        "USER": os.environ.get("DB_USER", "carflow"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "carflow-local-dev"),
        "HOST": os.environ.get("DB_HOST", "db"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}
