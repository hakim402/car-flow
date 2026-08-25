"""Grant the Phase 2 inventory movement permissions (README §8.1:
`inventory.transfer`). Codenames follow `{domain}.{action}`; the roles that
manage inventory receive move/transfer on top of their existing grants."""
from django.db import migrations

NEW_PERMISSIONS = ("inventory.move", "inventory.transfer")

# Roles that manage inventory at some level.
ROLE_KEYS = ("org_admin", "branch_manager", "inventory")


def seed(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in NEW_PERMISSIONS
    ]
    for role_key in ROLE_KEYS:
        role = Role.objects.filter(key=role_key).first()
        if role is None:
            continue
        role.permissions.add(*permissions)


def unseed(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    permissions = Permission.objects.filter(codename__in=NEW_PERMISSIONS)
    for role_key in ROLE_KEYS:
        role = Role.objects.filter(key=role_key).first()
        if role is not None:
            role.permissions.remove(*permissions)
    permissions.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_alter_user_managers"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
