"""Business Activity report page presentation."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.core.pagination import pagination_context

from .report_access import can_view_report
from .report_forms import ReportFilterForm
from .reporting import REPORTS, build_report


def report_url(key):
    return reverse("accounting:report", kwargs={"key": key})


def _number(value, *, places=2):
    try:
        return f"{Decimal(str(value)):,.{places}f}"
    except (InvalidOperation, ValueError, TypeError):
        return str(value) if value is not None else "—"


def _cell(column, row):
    value = row.get(column["key"])
    kind = column.get("kind", "text")
    if value is None or value == "":
        value = "—"
    elif kind == "money":
        value = _number(value)
        if row.get("currency"):
            value = f"{value} {row['currency']}"
    elif kind == "number":
        value = _number(value, places=0 if Decimal(str(value)) % 1 == 0 else 2)
    elif isinstance(value, datetime):
        value = date_format(value, "SHORT_DATETIME_FORMAT")
    elif isinstance(value, date):
        value = date_format(value, "SHORT_DATE_FORMAT")
    tone = None
    if column["key"] == "action":
        action_key = row.get("action_key")
        if action_key == "+":
            tone = "created"
        elif action_key == "-":
            tone = "deleted"
        else:
            tone = "updated"
    return {"key": column["key"], "label": column["label"], "value": value, "kind": kind, "tone": tone}


def prepare_report(report):
    """Add display-only values for the workspace template."""
    report = {**report, "metrics": [dict(item) for item in report.get("metrics", [])]}
    for metric in report["metrics"]:
        places = 2 if metric.get("currency") else 0
        metric["display_value"] = _number(metric["value"], places=places)
    charts = []
    for chart in report.get("charts", []):
        items = [dict(item) for item in chart.get("items", [])]
        largest = max((abs(Decimal(str(item["value"]))) for item in items), default=Decimal(0))
        for item in items:
            amount = Decimal(str(item["value"]))
            item["width"] = round(abs(amount) / largest * 100, 2) if largest else 0
            item["negative"] = amount < 0
            item["display_value"] = _number(amount, places=0)
        charts.append({**chart, "items": items})
    report["charts"] = charts
    return report


@login_required
@require_GET
@never_cache
def workspace(request, key="activity"):
    if key not in REPORTS:
        raise Http404
    if not can_view_report(request.user, key):
        raise PermissionDenied
    data = request.GET.copy()
    data.pop("page", None)
    form = ReportFilterForm(data, company=request.user.company, report_key=key)
    valid = form.is_valid()
    definition = REPORTS[key]
    report = {
        "key": key,
        "title": definition["title"],
        "description": definition["description"],
        "date_mode": definition["date_mode"],
        "columns": [],
        "rows": [],
        "metrics": [],
        "charts": [],
        "notes": [],
    }
    if valid:
        report = build_report(key, form.cleaned_data)
    rows = list(report["rows"])
    columns = [dict(column) for column in report["columns"]]
    sort = request.GET.get("sort", "")
    sort_key = sort.lstrip("-")
    if sort_key in {column["key"] for column in columns}:
        known = [row for row in rows if row.get(sort_key) is not None]
        unknown = [row for row in rows if row.get(sort_key) is None]
        known.sort(key=lambda row: row.get(sort_key), reverse=sort.startswith("-"))
        rows = known + unknown
    for column in columns:
        query = data.copy()
        query["sort"] = "-" + column["key"] if sort == column["key"] else column["key"]
        column.update(
            sort_url="?" + query.urlencode(),
            is_sorted=sort_key == column["key"],
            direction="descending" if sort.startswith("-") else "ascending",
        )
    page_size = int(request.GET.get("page_size", "20")) if request.GET.get("page_size") in {"20", "50", "100"} else 20
    pagination = pagination_context(request, rows, page_size=page_size)
    display_rows = [
        {
            "cells": [_cell(column, row) for column in columns],
            "url": row.get("_url"),
            "image": None,
            "actions": [],
        }
        for row in pagination["page_obj"]
    ]
    prepared_report = prepare_report(report)
    context = {
        **pagination,
        "report_data": prepared_report,
        "report_groups": [],
        "filter_form": form,
        "filters": data,
        "report_group_label": definition["group"],
        "hero_metric": None,
        "hero_chart_items": [],
        "show_report_records": True,
        "display_rows": display_rows,
        "columns": columns,
        "row_count": len(rows),
        "page_size": page_size,
        "filter_query": data.urlencode(),
        "report_url": report_url(key),
        "generated_at": timezone.now(),
        "is_paginated": pagination["page_obj"].paginator.num_pages > 1,
    }
    return render(request, "accounting/workspace.html", context, status=200 if valid else 400)
