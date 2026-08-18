# Ensure the Celery app is loaded when Django starts, so shared_task
# decorators bind to it and `celery -A config` finds it.
from .celery import app as celery_app  # noqa: E402,F401

# Register the integration-toggle system check (agent.md §12.1) at startup.
from . import checks  # noqa: E402,F401

__all__ = ["celery_app"]
