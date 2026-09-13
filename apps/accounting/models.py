"""Private, tenant-owned report snapshots. Never expose these through media URLs."""
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import TenantModel


class ReportExport(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Queued")
        RUNNING = "running", _("Preparing report")
        READY = "ready", _("Ready to download")
        FAILED = "failed", _("Export failed")
        EXPIRED = "expired", _("Expired")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    report_key = models.SlugField(max_length=40)
    format = models.CharField(max_length=8)
    language = models.CharField(max_length=8, default="en")
    snapshot = models.JSONField(default=dict)
    row_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    # Database storage intentionally avoids public MEDIA/S3 URLs and works across
    # worker/web containers without a new filesystem-sharing prerequisite.
    file_content = models.BinaryField(default=bytes, editable=False)
    error = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    company_relations = ("created_by",)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "created_by", "created_at"], name="acc_export_owner_created")]


class ReportShare(TenantModel):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    report_key = models.SlugField(max_length=40)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    language = models.CharField(max_length=8, default="en")
    snapshot = models.JSONField(default=dict)
    columns = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    access_count = models.PositiveIntegerField(default=0)
    last_access_at = models.DateTimeField(null=True, blank=True)
    company_relations = ("created_by",)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "created_by", "created_at"], name="acc_share_owner_created")]

    @property
    def active(self):
        return not self.revoked_at and self.expires_at > timezone.now()


class ReportShareAccess(TenantModel):
    """A minimal access trail without retaining visitors' raw network addresses."""
    share = models.ForeignKey(ReportShare, on_delete=models.CASCADE, related_name="accesses")
    accessed_at = models.DateTimeField(default=timezone.now, db_index=True)
    company_relations = ("share",)

    class Meta:
        ordering = ["-accessed_at"]
