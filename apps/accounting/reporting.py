"""Tenant-scoped Business Activity report dataset.

The report catalog was intentionally reduced to a single audit-style page.
Deleted financial and business report keys are absent from REPORTS and fail
closed in build_report.
"""

from django.db import connection, transaction
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from apps.core.tenancy import get_current_company, NoTenantContext
from apps.purchases.models import PurchaseOrder
from apps.sales.models import Lead, Quotation, Reservation, Sale


def _definition(title, description, group, permission, date_mode, **extra):
    return dict(title=title, description=description, group=group, permission=permission, date_mode=date_mode, **extra)


REPORTS = {
    "activity": _definition(
        gettext_lazy("Business Activity"),
        gettext_lazy("Recorded business changes and their responsible staff."),
        gettext_lazy("Operations Reports"),
        "reports.activity",
        "period",
    ),
}


def _column(key, label, kind="text"):
    return {"key": key, "label": label, "kind": kind}


def _report(key, columns, rows, metrics=None, charts=None, notes=None):
    definition = REPORTS[key]
    return {
        "key": key,
        "title": str(definition["title"]),
        "description": str(definition["description"]),
        "date_mode": definition["date_mode"],
        "columns": columns,
        "rows": rows,
        "metrics": metrics or [],
        "charts": charts or [],
        "notes": notes or [],
    }


def _period(qs, field, filters, *, datetime=False):
    field = f"{field}__date" if datetime else field
    if filters.get("date_from"):
        qs = qs.filter(**{f"{field}__gte": filters["date_from"]})
    if filters.get("date_to"):
        qs = qs.filter(**{f"{field}__lte": filters["date_to"]})
    return qs


def _branch(qs, field, filters):
    return qs.filter(**{field: filters["branch"]}) if filters.get("branch") else qs


def _activity(filters):
    from apps.customers.models import Customer
    from apps.inventory.models import InventoryLocation, VehicleStock
    from apps.suppliers.models import Supplier
    from apps.vehicles.models import Vehicle

    company = get_current_company()
    sources = [
        (Vehicle, _("Vehicle"), _("Buy and stock"), "stock", "branch_id"),
        (VehicleStock, _("Stock"), _("Buy and stock"), "stock", "branch_id"),
        (InventoryLocation, _("Location"), _("Buy and stock"), "stock", "branch_id"),
        (Customer, _("Customer"), _("Customer records"), "customers", "branch_id"),
        (Supplier, _("Supplier"), _("Supplier records"), "suppliers", None),
        (PurchaseOrder, _("Purchase order"), _("Buy and stock"), "stock", "branch_id"),
        (Lead, _("Lead"), _("Sales"), "sales", "branch_id"),
        (Quotation, _("Quotation"), _("Sales"), "sales", "customer__branch_id"),
        (Reservation, _("Reservation"), _("Sales"), "sales", "customer__branch_id"),
        (Sale, _("Sale"), _("Sales"), "sales", "customer__branch_id"),
    ]
    rows = []
    action_labels = {"+": _("Created"), "~": _("Updated"), "-": _("Deleted")}
    for model, label, area, module_key, branch_field in sources:
        if filters.get("module") and filters["module"] != module_key:
            continue
        qs = model.history.filter(company_id=company.pk).select_related("history_user")
        if filters.get("action"):
            qs = qs.filter(history_type=filters["action"])
        if filters.get("branch"):
            if not branch_field:
                continue
            qs = _branch(qs, branch_field, filters)
        qs = _period(qs, "history_date", filters, datetime=True)
        for event in qs:
            actor = (
                event.history_user.get_full_name()
                or event.history_user.username
                or _("Staff user")
                if event.history_user
                else _("System / unknown")
            )
            action = action_labels[event.history_type]
            recorded_at = timezone.localtime(event.history_date)
            reference = f"#{event.id}"
            summary = f"{label} {reference} · {action}"
            search_text = f"{area} {label} {reference} {action} {actor}"
            if filters.get("q") and filters["q"].casefold() not in search_text.casefold():
                continue
            rows.append({
                "summary": summary,
                "area": area,
                "module_key": module_key,
                "record_type": label,
                "reference": reference,
                "action": action,
                "action_key": event.history_type,
                "date": recorded_at,
                "day": recorded_at.date(),
                "staff": actor,
                "count": 1,
            })
    rows.sort(key=lambda row: row["date"], reverse=True)
    return _report(
        "activity",
        [
            _column("summary", _("Change")),
            _column("area", _("Workspace")),
            _column("record_type", _("Record type")),
            _column("reference", _("Reference")),
            _column("action", _("Action")),
            _column("date", _("Recorded at")),
            _column("staff", _("Responsible staff")),
        ],
        rows,
        [],
        [],
        [
            _("This report covers models registered with business history. Immutable financial entries, login events and report access logs are separate records."),
            _("The period uses history timestamps. Action and workspace filters narrow the audit trail without changing the underlying records. Missing actors remain explicitly unknown."),
        ],
    )


_BUILDERS = {"activity": _activity}


def build_report(key, filters):
    """Build the entire filtered activity dataset, never just a displayed page."""
    if get_current_company() is None:
        raise NoTenantContext("A company context is required for reports.")
    if key not in REPORTS:
        raise KeyError(key)
    if connection.vendor == "postgresql" and not connection.in_atomic_block:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return _BUILDERS[key](filters)
    return _BUILDERS[key](filters)
