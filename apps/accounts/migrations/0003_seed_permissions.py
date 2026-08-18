"""Seed granular Permissions and grant them to the built-in roles (agent.md §8).

Codenames follow `{app}.{action}`; business views check them via
apps.core.decorators.require_permission for object-level, tenant-scoped
access. Super Admin bypasses checks (is_superuser semantics in User).
"""
from django.db import migrations

APPS = (
    "vehicles",
    "inventory",
    "suppliers",
    "purchases",
    "customers",
    "sales",
    "payments",
    "expenses",
    "communications",
    "documents",
)
ACTIONS = ("view", "add", "change")

# role key → list of codenames granted.
ROLE_GRANTS = {
    # Org admins manage everything inside their tenant.
    "org_admin": [f"{app}.{action}" for app in APPS for action in ACTIONS],
    "branch_manager": [
        f"{app}.{action}"
        for app in ("vehicles", "inventory", "customers", "sales")
        for action in ACTIONS
    ]
    + [f"communications.{action}" for action in ACTIONS]
    + ["payments.view", "expenses.view", "documents.view", "documents.add"],
    "sales": [
        "vehicles.view",
        "customers.view",
        "customers.add",
        "customers.change",
        "sales.view",
        "sales.add",
        "sales.change",
        "communications.view",
        "communications.add",
        "documents.view",
        "documents.add",
    ],
    "inventory": [
        f"{app}.{action}"
        for app in ("vehicles", "inventory")
        for action in ACTIONS
    ]
    + ["purchases.view", "documents.view", "documents.add"],
    "accountant": [
        f"{app}.{action}" for app in ("payments", "expenses") for action in ACTIONS
    ]
    + ["sales.view", "purchases.view", "customers.view", "vehicles.view"],
}


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    for codename in {c for grants in ROLE_GRANTS.values() for c in grants}:
        Permission.objects.get_or_create(codename=codename)
    for role_key, codenames in ROLE_GRANTS.items():
        role = Role.objects.filter(key=role_key).first()
        if role is None:
            continue
        role.permissions.set(Permission.objects.filter(codename__in=codenames))


def unseed_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    codenames = {c for grants in ROLE_GRANTS.values() for c in grants}
    Permission.objects.filter(codename__in=codenames).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_seed_builtin_roles"),
    ]

    operations = [
        migrations.RunPython(seed_permissions, unseed_permissions),
    ]
