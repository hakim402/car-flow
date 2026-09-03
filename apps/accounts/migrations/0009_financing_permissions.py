from django.db import migrations


PERMISSIONS = (
    "financing.view",
    "financing.add",
    "financing.change",
    "financing.approve",
    "financing.collect",
    "financing.default",
)

ROLE_GRANTS = {
    "org_admin": PERMISSIONS,
    "branch_manager": PERMISSIONS,
    "sales": ("financing.view", "financing.add", "financing.change"),
    "accountant": ("financing.view", "financing.collect"),
    "finance_officer": PERMISSIONS,
}


def seed_financing_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    permissions = {
        codename: Permission.objects.get_or_create(codename=codename)[0]
        for codename in PERMISSIONS
    }
    finance_role, _ = Role.objects.get_or_create(
        key="finance_officer",
        defaults={"name": "Finance Officer", "system": True},
    )
    finance_role.system = True
    finance_role.save(update_fields=["system"])
    for role_key, codenames in ROLE_GRANTS.items():
        role = Role.objects.filter(key=role_key).first()
        if role:
            role.permissions.add(*(permissions[codename] for codename in codenames))


def unseed_financing_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(key="finance_officer").delete()
    Permission.objects.filter(codename__in=PERMISSIONS).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_inventory_move_transfer_permissions")]
    operations = [migrations.RunPython(seed_financing_permissions, unseed_financing_permissions)]
