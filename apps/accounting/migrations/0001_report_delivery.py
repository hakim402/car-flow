import apps.core.models
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def seed_report_permissions(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    for codename, roles in (("reports.share", ("org_admin", "accountant")), ("reports.activity", ("org_admin",))):
        permission, _ = Permission.objects.get_or_create(codename=codename)
        for role in Role.objects.filter(key__in=roles):
            role.permissions.add(permission)


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("organizations", "0001_initial"),
        ("accounts", "0010_money_workspace_permissions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ReportExport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("report_key", models.SlugField(max_length=40)),
                ("format", models.CharField(max_length=8)),
                ("language", models.CharField(default="en", max_length=8)),
                ("snapshot", models.JSONField(default=dict)),
                ("row_count", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(choices=[("pending", "Queued"), ("running", "Preparing report"), ("ready", "Ready to download"), ("failed", "Export failed"), ("expired", "Expired")], default="pending", max_length=12)),
                ("file_content", models.BinaryField(default=bytes)),
                ("error", models.CharField(blank=True, max_length=255)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organizations.organization", verbose_name="company")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"], "indexes": [models.Index(fields=["company", "created_by", "created_at"], name="acc_export_owner_created")]},
            bases=(apps.core.models.CompanyConsistencyMixin, models.Model),
        ),
        migrations.CreateModel(
            name="ReportShare",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("report_key", models.SlugField(max_length=40)),
                ("token_hash", models.CharField(editable=False, max_length=64, unique=True)),
                ("language", models.CharField(default="en", max_length=8)),
                ("snapshot", models.JSONField(default=dict)),
                ("columns", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("access_count", models.PositiveIntegerField(default=0)),
                ("last_access_at", models.DateTimeField(blank=True, null=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organizations.organization", verbose_name="company")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"], "indexes": [models.Index(fields=["company", "created_by", "created_at"], name="acc_share_owner_created")]},
            bases=(apps.core.models.CompanyConsistencyMixin, models.Model),
        ),
        migrations.CreateModel(
            name="ReportShareAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("accessed_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organizations.organization", verbose_name="company")),
                ("share", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="accesses", to="accounting.reportshare")),
            ],
            options={"ordering": ["-accessed_at"]},
            bases=(apps.core.models.CompanyConsistencyMixin, models.Model),
        ),
        # A rollback must not remove permissions now used by custom roles.
        migrations.RunPython(seed_report_permissions, migrations.RunPython.noop),
    ]
