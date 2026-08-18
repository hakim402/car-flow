"""Startup validation for third-party integration toggles (agent.md §12.1).

Rules enforced here:
- *_ENABLED=False → credential variables may be blank; booting must succeed.
- *_ENABLED=True  → every required credential must be present, otherwise a
  clear, actionable error fails startup fast (never deep inside send-time).

Registered as a Django system check so `runserver`, `migrate`, and `check`
all refuse to proceed with a half-configured integration.
"""
from django.conf import settings
from django.core.checks import Error, Tags, register

# Enable flag → credential settings that must be non-blank when the flag is on.
INTEGRATION_REQUIREMENTS: dict[str, list[str]] = {
    "META_ENABLED": [
        "META_APP_ID",
        "META_APP_SECRET",
        "META_ACCESS_TOKEN",
        "META_WEBHOOK_VERIFY_TOKEN",
    ],
    "TELEGRAM_ENABLED": ["TELEGRAM_BOT_TOKEN"],
    "SMS_ENABLED": ["SMS_GATEWAY_URL", "SMS_GATEWAY_API_KEY"],
    "EMAIL_ENABLED": ["EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD"],
    "S3_ENABLED": [
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_BUCKET_NAME",
    ],
}


@register(Tags.security)
def integration_credentials_check(app_configs=None, **kwargs):
    """Fail fast with a named-variable error when an enabled integration is
    missing any required credential; stay silent when everything is off."""
    errors = []
    for flag, required in INTEGRATION_REQUIREMENTS.items():
        if not getattr(settings, flag, False):
            continue
        missing = [name for name in required if not getattr(settings, name, "")]
        if missing:
            errors.append(
                Error(
                    f"{flag}=True but {', '.join(missing)} "
                    f"{'is' if len(missing) == 1 else 'are'} not set.",
                    hint="Add the missing values to .env and restart the containers, "
                    f"or set {flag}=False to run without this integration.",
                    id="carflow.E001",
                )
            )
    return errors
