from django.db import migrations


PERMISSIONS = (
    "payments.reverse",
    "payments.export",
    "payments.accounts_manage",
    "expenses.reverse",
    "expenses.manage_categories",
    "reports.export",
)

ROLE_GRANTS = {
    "org_admin": PERMISSIONS,
    "accountant": PERMISSIONS,
    "finance_officer": ("payments.reverse", "payments.export", "reports.export"),
}


def seed_money_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    permissions = {
        codename: Permission.objects.get_or_create(codename=codename)[0]
        for codename in PERMISSIONS
    }
    for role_key, codenames in ROLE_GRANTS.items():
        role = Role.objects.filter(key=role_key).first()
        if role:
            role.permissions.add(*(permissions[codename] for codename in codenames))


def unseed_money_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Permission.objects.filter(codename__in=PERMISSIONS).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_financing_permissions")]
    operations = [migrations.RunPython(seed_money_permissions, unseed_money_permissions)]
