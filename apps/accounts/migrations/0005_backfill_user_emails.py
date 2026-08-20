"""Backfill an email for every existing user so 0006 can add UNIQUE.

Generated addresses are placeholders (<username>@automex.local) — users
change them via Django Admin or `manage.py changepassword`-style flows.
"""
from django.db import migrations


def backfill_emails(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.all():
        if not user.email:
            base = user.username or f"user{user.pk}"
            user.email = f"{base}@automex.local"
            user.save(update_fields=["email"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_email_login_prepare"),
    ]

    operations = [
        migrations.RunPython(backfill_emails, migrations.RunPython.noop),
    ]
