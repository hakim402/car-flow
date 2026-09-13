"""Bounded report rendering and retention, running in the existing Docker worker."""
import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone, translation

from apps.core.tenancy import company_scope

from .exports import render_export
from .models import ReportExport, ReportShare, ReportShareAccess

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, soft_time_limit=150, time_limit=180)
def generate_report_export(self, export_id):
    from .report_access import can_deliver_report
    # Trusted task ID resolves the tenant from storage; never from task clients.
    job = ReportExport.all_objects.select_related("company", "created_by").filter(pk=export_id).first()
    if not job:
        return
    with company_scope(job.company):
        with transaction.atomic():
            job = ReportExport.objects.select_for_update().get(pk=export_id)
            now = timezone.now()
            if job.expires_at <= now:
                ReportExport.objects.filter(pk=job.pk).update(status="expired", snapshot={}, file_content=b"")
                return
            if job.status in {"ready", "expired"}:
                return
            if job.status == "running" and job.started_at and job.started_at > now - timedelta(minutes=4):
                return
            if job.created_by.company_id != job.company_id or not can_deliver_report(job.created_by, job.report_key, "export"):
                ReportExport.objects.filter(pk=job.pk).update(status="failed", error="permission", snapshot={}, file_content=b"")
                return
            ReportExport.objects.filter(pk=job.pk).update(status="running", started_at=now, attempts=job.attempts + 1, error="")
        try:
            with translation.override(job.language):
                result = render_export(job.snapshot, job.format)
            # Permission and expiration can change while a large file renders.
            job.created_by.refresh_from_db()
            if job.created_by.company_id != job.company_id or not can_deliver_report(job.created_by, job.report_key, "export"):
                ReportExport.objects.filter(pk=job.pk).update(status="failed", error="permission", snapshot={}, file_content=b"")
                return
            if job.expires_at <= timezone.now():
                ReportExport.objects.filter(pk=job.pk).update(status="expired", snapshot={}, file_content=b"")
                return
            ReportExport.objects.filter(pk=job.pk).update(status="ready", file_content=result, completed_at=timezone.now(), error="")
        except Exception as exc:
            # Error details stay in worker logs, never in downloads or snapshots.
            logger.exception("Report export %s failed", job.pk)
            if self.request.retries < self.max_retries:
                ReportExport.objects.filter(pk=job.pk).update(status="pending", error="retry")
                raise self.retry(exc=exc, countdown=15 * (self.request.retries + 1))
            ReportExport.objects.filter(pk=job.pk).update(status="failed", error="render")


@shared_task
def cleanup_report_delivery():
    """Purge expired payloads; retain only 30 days of delivery/access metadata."""
    now = timezone.now()
    # Cross-tenant retention is deliberate system work, with no client filters.
    ReportExport.all_objects.filter(expires_at__lte=now).exclude(status="expired").update(
        status="expired", file_content=b"", snapshot={})
    ReportShare.all_objects.filter(expires_at__lte=now).exclude(snapshot={}).update(snapshot={})
    ReportShare.all_objects.filter(revoked_at__isnull=False).exclude(snapshot={}).update(snapshot={})
    cutoff = now - timedelta(days=30)
    ReportShareAccess.all_objects.filter(accessed_at__lt=cutoff).delete()
    ReportExport.all_objects.filter(expires_at__lt=cutoff).delete()
    ReportShare.all_objects.filter(expires_at__lt=cutoff).delete()
