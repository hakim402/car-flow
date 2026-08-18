"""Dev verification for the §12.1 gate: META_ENABLED=True with blank
credentials must fail `check` fast with a named-variable error."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["META_ENABLED"] = "True"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

from django.core.management import execute_from_command_line  # noqa: E402

try:
    execute_from_command_line(["manage.py", "check"])
except SystemExit as exc:
    sys.exit(exc.code)
