"""Seed the six Phase 1 built-in roles (agent.md §8). Custom roles arrive in
Phase 2 as regular rows — the schema already supports them."""
from django.db import migrations

BUILTIN_ROLES = [
    ("super_admin", "Super Admin"),
    ("org_admin", "Organization Admin"),
    ("branch_manager", "Branch Manager"),
    ("sales", "Sales"),
    ("inventory", "Inventory"),
    ("accountant", "Accountant"),
]


def seed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for key, name in BUILTIN_ROLES:
        Role.objects.update_or_create(key=key, defaults={"name": name, "system": True})


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(key__in=[key for key, _ in BUILTIN_ROLES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_roles, unseed_roles),
    ]
