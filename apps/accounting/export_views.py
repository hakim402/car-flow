"""Authenticated private exports and explicitly scoped, revocable public snapshots."""
import hashlib
import re
import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.core.tenancy import company_scope

from .exports import FORMATS, display, freeze_report, public_snapshot
from .models import ReportExport, ReportShare, ReportShareAccess
from .report_access import can_deliver_report
from .report_forms import ReportFilterForm
from .reporting import REPORTS, build_report
from .tasks import generate_report_export


def _headers(response, *, public=False):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["X-Content-Type-Options"] = "nosniff"
    if public:
        response["Content-Security-Policy"] = "default-src 'self'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; form-action 'none'; base-uri 'none'"
    return response


def _failure(request, message, *, status=400, public=False):
    return _headers(render(request, "accounting/delivery_error.html", {
        "error": message, "is_public": public,
        "history_url": reverse("accounting:delivery_history"),
    }, status=status), public=public)


def _access(user, key, action):
    if key not in REPORTS:
        raise Http404
    if not can_deliver_report(user, key, action):
        raise PermissionDenied


def _snapshot(request, key):
    form = ReportFilterForm(request.GET, company=request.user.company, report_key=key)
    if not form.is_valid():
        raise ValueError(_("The report filters are invalid. Check the dates, branch and currency."))
    with company_scope(request.user.company):
        report = build_report(key, form.cleaned_data)
        start, end = form.cleaned_data.get("date_from"), form.cleaned_data.get("date_to")
        if request.GET.get("compare") == "1" and REPORTS[key]["date_mode"] == "period" and start and end:
            length = (end - start).days + 1
            if start.toordinal() > length:
                previous = build_report(key, {**form.cleaned_data, "date_from": start - timedelta(days=length), "date_to": start - timedelta(days=1)})
                previous_metrics = {(str(item["label"]), item.get("currency", "")): item for item in previous["metrics"]}
                comparison = []
                for item in report["metrics"]:
                    prior = previous_metrics.get((str(item["label"]), item.get("currency", "")))
                    if prior:
                        comparison.extend([
                            {**item, "label": f"{item['label']} — {_('Previous period')}", "value": prior["value"]},
                            {**item, "label": f"{item['label']} — {_('Change')}", "value": Decimal(str(item["value"])) - Decimal(str(prior["value"]))},
                        ])
                report["metrics"] = [*report["metrics"], *comparison]
        sort = request.GET.get("sort", "")
        sort_key = sort.lstrip("-")
        if sort_key in {column["key"] for column in report["columns"]}:
            present = [row for row in report["rows"] if row.get(sort_key) is not None]
            missing = [row for row in report["rows"] if row.get(sort_key) is None]
            report["rows"] = sorted(present, key=lambda row: row[sort_key], reverse=sort.startswith("-")) + missing
        filters = {k: (str(v) if hasattr(v, "pk") else v) for k, v in form.cleaned_data.items() if v not in (None, "")}
        for field in ("branch", "category"):
            if filters.get(field) and field in form.fields:
                filters[field] = dict(form.fields[field].choices).get(str(filters[field]), filters[field])
        return freeze_report(report, company_name=request.user.company.name,
                             language=translation.get_language() or "en", filters=filters)


@login_required
@require_POST
@never_cache
def export_create(request, key):
    _access(request.user, key, "export")
    format = request.POST.get("format", "")
    if format not in FORMATS:
        return _failure(request, _("Choose PDF, XLSX, DOCX or CSV."))
    with company_scope(request.user.company):
        # Per-user bounds prevent accidental double clicks from filling storage.
        if ReportExport.objects.filter(created_by=request.user, status__in=["pending", "running"], expires_at__gt=timezone.now()).count() >= 3:
            return _failure(request, _("You already have three reports preparing. Wait for one to finish."), status=429)
        try:
            snapshot = _snapshot(request, key)
        except ValueError as exc:
            return _failure(request, str(exc))
        job = ReportExport.objects.create(
            company=request.user.company, created_by=request.user, report_key=key,
            format=format, language=snapshot["language"], snapshot=snapshot,
            row_count=len(snapshot["rows"]), expires_at=timezone.now() + timedelta(hours=24))
        try:
            generate_report_export.delay(job.pk)
        except Exception:
            ReportExport.objects.filter(pk=job.pk).update(status="failed", error="queue")
        return redirect("accounting:export_status", pk=job.pk)


def _owned_export(request, pk):
    if not getattr(request.user, "company_id", None):
        raise PermissionDenied
    with company_scope(request.user.company):
        job = get_object_or_404(ReportExport.objects.select_related("company"), pk=pk, created_by=request.user)
        _access(request.user, job.report_key, "export")
        if job.expires_at <= timezone.now() and job.status != "expired":
            ReportExport.objects.filter(pk=job.pk).update(status="expired", file_content=b"", snapshot={})
            job.status = "expired"; job.snapshot = {}; job.file_content = b""
        return job


@login_required
@require_GET
@never_cache
def export_status(request, pk):
    job = _owned_export(request, pk)
    status_url = reverse("accounting:export_status", kwargs={"pk": job.pk})
    download_url = reverse("accounting:export_download", kwargs={"pk": job.pk})
    report_title = job.snapshot.get("title") or REPORTS.get(job.report_key, {}).get("title", _("Report"))
    if request.GET.get("json") == "1":
        return _headers(JsonResponse({"status": job.status, "label": job.get_status_display(),
                                      "download_url": download_url if job.status == "ready" else None}))
    return _headers(render(request, "accounting/export_status.html", {
        "export_job": job, "status_url": status_url, "download_url": download_url,
        "history_url": reverse("accounting:delivery_history"), "report_title": report_title,
    }))


@login_required
@require_GET
@never_cache
def export_download(request, pk):
    job = _owned_export(request, pk)
    if job.status != "ready" or not job.file_content:
        return _failure(request, _("This export is not available. It may still be preparing or may have expired."), status=410)
    response = HttpResponse(bytes(job.file_content), content_type=FORMATS[job.format])
    response["Content-Disposition"] = f'attachment; filename="AMOXRUNS-{job.report_key}-{job.pk}.{job.format}"'
    return _headers(response)


@login_required
@require_POST
@never_cache
def share_create(request, key):
    _access(request.user, key, "share")
    try:
        lifetime = int(request.POST.get("expires_in", "3600"))
        if lifetime not in (3600, 86400, 604800):
            raise ValueError
    except (TypeError, ValueError):
        return _failure(request, _("Choose a link lifetime of one hour, one day or seven days."))
    with company_scope(request.user.company):
        if ReportShare.objects.filter(created_by=request.user, revoked_at__isnull=True, expires_at__gt=timezone.now()).count() >= 20:
            return _failure(request, _("Revoke an existing share link before creating another."), status=429)
        try:
            snapshot = public_snapshot(_snapshot(request, key), request.POST.getlist("columns"))
        except ValueError as exc:
            return _failure(request, str(exc))
        token = secrets.token_urlsafe(32)
        share = ReportShare.objects.create(
            company=request.user.company, created_by=request.user, report_key=key,
            token_hash=hashlib.sha256(token.encode()).hexdigest(), language=snapshot["language"],
            snapshot=snapshot, columns=[c["key"] for c in snapshot["columns"]],
            expires_at=timezone.now() + timedelta(seconds=lifetime))
        # The raw token is shown exactly once and is never persisted in the DB.
        url = request.build_absolute_uri(reverse("accounting:shared_report", kwargs={"token": token}))
        return _headers(render(request, "accounting/share_created.html", {
            "share": share, "share_url": url, "report_data": snapshot,
            "history_url": reverse("accounting:delivery_history"),
        }, status=201))


@require_GET
@never_cache
def shared_report(request, token):
    unavailable = _("This report link is unavailable, expired or revoked.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return _failure(request, unavailable, status=404, public=True)
    # Only this cryptographic capability lookup crosses tenants. All later work
    # uses the fixed company and frozen data stored on the validated record.
    share = ReportShare.all_objects.select_related("company", "created_by").filter(
        token_hash=hashlib.sha256(token.encode()).hexdigest(), revoked_at__isnull=True,
        expires_at__gt=timezone.now()).first()
    if not share or not share.snapshot or share.created_by.company_id != share.company_id or not can_deliver_report(share.created_by, share.report_key, "share"):
        return _failure(request, unavailable, status=404, public=True)
    with company_scope(share.company), translation.override(share.language):
        ReportShare.objects.filter(pk=share.pk).update(access_count=F("access_count") + 1, last_access_at=timezone.now())
        ReportShareAccess.objects.create(company=share.company, share=share)
        page = Paginator(share.snapshot["rows"], 25).get_page(request.GET.get("page"))
        rows = [{"cells": [{"value": display(row.get(c["key"]), c.get("kind")), "kind": c.get("kind", "text"), "label": c["label"]}
                            for c in share.snapshot["columns"]]} for row in page]
        report_data = {**share.snapshot, "rows": list(page)}
        return _headers(render(request, "accounting/shared_report.html", {
            "share": share, "report_data": report_data, "snapshot": report_data,
            "company_name": share.snapshot["company_name"], "page_obj": page,
            "display_rows": rows, "LANGUAGE_CODE": share.language,
            "LANGUAGE_BIDI": share.language in {"prs", "ps"},
        }), public=True)


@login_required
@require_POST
@never_cache
def share_revoke(request, pk):
    if not getattr(request.user, "company_id", None):
        raise PermissionDenied
    with company_scope(request.user.company):
        share = get_object_or_404(ReportShare.objects, pk=pk, created_by=request.user)
        # The creator can always retract their own disclosure even if their
        # sharing permission was subsequently removed.
        ReportShare.objects.filter(pk=share.pk).update(revoked_at=timezone.now(), snapshot={})
    return redirect("accounting:delivery_history")


@login_required
@require_GET
@never_cache
def delivery_history(request):
    if not getattr(request.user, "company_id", None):
        raise PermissionDenied
    with company_scope(request.user.company):
        allowed_export = [key for key in REPORTS if can_deliver_report(request.user, key, "export")]
        allowed_delivery = [
            key for key in REPORTS
            if can_deliver_report(request.user, key, "export") or can_deliver_report(request.user, key, "share")
        ]
        exports = list(ReportExport.objects.filter(created_by=request.user, report_key__in=allowed_export).defer("file_content", "snapshot")[:50])
        # Revocation remains available after permissions change. No underlying
        # snapshot, company data or raw token is exposed in this metadata list.
        shares = list(ReportShare.objects.filter(created_by=request.user, report_key__in=allowed_delivery).defer("snapshot", "token_hash")[:50])
        for item in [*exports, *shares]:
            item.report_title = REPORTS.get(item.report_key, {}).get("title", _("Report"))
            if isinstance(item, ReportExport) and item.expires_at <= timezone.now():
                item.status = "expired"
        return _headers(render(request, "accounting/delivery_history.html", {
            "exports": exports, "shares": shares, "report_catalog": REPORTS,
        }))
