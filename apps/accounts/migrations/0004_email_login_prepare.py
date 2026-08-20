"""Email becomes the login identifier (§8): username turns optional.

The unique constraint on email is added in 0006, AFTER 0005 backfills an
email for every existing user (unique indexes cannot be built over
duplicate empty strings).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_seed_permissions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(
                blank=True, max_length=150, null=True, verbose_name="username"
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(max_length=254, verbose_name="email"),
        ),
        migrations.AlterModelOptions(
            name="user",
            options={"ordering": ["email"], "verbose_name": "user", "verbose_name_plural": "users"},
        ),
    ]
