from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

# Session key LocaleMiddleware used before Django switched the canonical
# storage to the LANGUAGE_COOKIE; we still set it for backwards compatibility.
LANGUAGE_SESSION_KEY = "django_language"


def _language_cookie_response(response, language: str):
    """Persist the language choice where Django 5's LocaleMiddleware actually
    reads it: the `django_language` COOKIE (session alone is ignored)."""
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language,
        max_age=60 * 60 * 24 * 365,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )
    return response


class AmoxrunsLoginView(auth_views.LoginView):
    """Login by email (USERNAME_FIELD) that also activates the user's stored
    preferred_language (§11.2) immediately after authentication."""

    template_name = "accounts/login.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        language = getattr(self.request.user, "preferred_language", "") or ""
        if language in {code for code, _name in settings.LANGUAGES}:
            if hasattr(self.request, "session"):
                self.request.session[LANGUAGE_SESSION_KEY] = language
            response = _language_cookie_response(response, language)
        return response


@login_required
def dashboard(request):
    """Post-login landing screen: company KPIs, quick actions and the latest
    sales. Tenant scoping is automatic — TenantMiddleware filters `objects`
    to the user's company, while Super Admin (no company) sees platform-wide
    totals through the explicit `all_objects` escape hatch (§25.1)."""
    # Imports stay local: this view lives in the auth app and must not drag
    # the business models into its module-import graph at startup.
    from apps.accounting.services import ledger_balance, money_in, money_out, sale_payment_summaries
    from apps.customers.models import Customer
    from apps.inventory.models import StockStatus, VehicleStock
    from apps.payments.models import LedgerEntry
    from apps.sales.models import Lead, LeadStatus, Reservation, ReservationStatus, Sale, SaleStatus

    if request.user.company_id is None:
        # Super Admin runs without tenant context: unrestricted access must
        # be an explicit all_objects choice, never the tenant manager (§25.1).
        lead_qs, sale_qs, customer_qs, stock_qs, reservation_qs = (
            Lead.all_objects,
            Sale.all_objects,
            Customer.all_objects,
            VehicleStock.all_objects,
            Reservation.all_objects,
        )
        cash_position = ledger_balance(company=None)
        money_in_total = money_in(company=None)
        money_out_total = money_out(company=None)
    else:
        lead_qs, sale_qs, customer_qs, stock_qs, reservation_qs = (
            Lead.objects,
            Sale.objects,
            Customer.objects,
            VehicleStock.objects,
            Reservation.objects,
        )
        cash_position = ledger_balance(company=request.user.company)
        money_in_total = money_in(company=request.user.company)
        money_out_total = money_out(company=request.user.company)

    today = timezone.localdate()
    trend_start = today - timedelta(days=13)
    recent_entries = list(
        LedgerEntry.objects.filter(transaction_date__gte=today - timedelta(days=6))
        if request.user.company_id is not None
        else LedgerEntry.all_objects.filter(transaction_date__gte=today - timedelta(days=6))
    )
    completed_sales_qs = sale_qs.filter(status=SaleStatus.COMPLETED)
    sales_by_currency = completed_sales_qs.values("currency").annotate(total=Sum("agreed_amount")).order_by("-total", "currency")
    primary_currency = (sales_by_currency[0]["currency"] if sales_by_currency else (next(iter(cash_position.keys()), "USD")))
    sales_daily = {
        item["day"]: item
        for item in completed_sales_qs.filter(sale_date__gte=trend_start, currency=primary_currency)
        .annotate(day=TruncDate("sale_date"))
        .values("day")
        .annotate(total=Sum("agreed_amount"), count=Count("id"))
        .order_by("day")
    }
    sales_trend = []
    max_revenue = Decimal("1")
    max_sales_count = 1
    for index in range(14):
        day = trend_start + timedelta(days=index)
        item = sales_daily.get(day, {})
        revenue = item.get("total") or Decimal("0")
        count = item.get("count") or 0
        max_revenue = max(max_revenue, revenue)
        max_sales_count = max(max_sales_count, count)
        sales_trend.append({"date": day, "revenue": revenue, "count": count})
    chart_width, chart_height, chart_top, chart_left = Decimal("840"), Decimal("220"), Decimal("24"), Decimal("40")
    chart_bottom = chart_top + chart_height
    revenue_points, sales_count_points = [], []
    for index, item in enumerate(sales_trend):
        x = chart_left + (Decimal(index) * (chart_width / Decimal(max(len(sales_trend) - 1, 1))))
        revenue_y = chart_bottom - ((item["revenue"] / max_revenue) * chart_height)
        sales_y = chart_bottom - ((Decimal(item["count"]) / Decimal(max_sales_count)) * chart_height)
        item["x"] = f"{x:.2f}"
        item["revenue_y"] = f"{revenue_y:.2f}"
        item["sales_y"] = f"{sales_y:.2f}"
        item["revenue_display"] = f"{item['revenue']:.0f}"
        item["label"] = date_format(day, "M j")
        revenue_points.append(f"{x:.2f},{revenue_y:.2f}")
        sales_count_points.append(f"{x:.2f},{sales_y:.2f}")
    revenue_area_points = " ".join([f"{chart_left:.2f},{chart_bottom:.2f}", *revenue_points, f"{(chart_left + chart_width):.2f},{chart_bottom:.2f}"])
    inventory_counts = {
        status: stock_qs.filter(status=status).count()
        for status, _label in StockStatus.choices
    }
    inventory_total = sum(inventory_counts.values())
    inventory_denominator = inventory_total or 1
    inventory_mix = [
        {"label": _("Available"), "value": inventory_counts.get(StockStatus.AVAILABLE, 0), "color": "brand"},
        {"label": _("Reserved"), "value": inventory_counts.get(StockStatus.RESERVED, 0), "color": "amber"},
        {"label": _("Sold pending delivery"), "value": inventory_counts.get(StockStatus.SOLD, 0), "color": "emerald"},
        {
            "label": _("In process"),
            "value": sum(inventory_counts.get(status, 0) for status in [StockStatus.IN_TRANSIT, StockStatus.RECEIVED, StockStatus.INSPECTION, StockStatus.PREPARATION]),
            "color": "slate",
        },
    ]
    inventory_offset = 0
    for item in inventory_mix:
        item["width"] = round((item["value"] / inventory_denominator) * 100, 2)
        item["offset"] = -inventory_offset
        inventory_offset += item["width"]
    lead_pipeline = [
        {"label": _("New"), "value": lead_qs.filter(status=LeadStatus.NEW).count()},
        {"label": _("Contacted"), "value": lead_qs.filter(status=LeadStatus.CONTACTED).count()},
        {"label": _("Qualified"), "value": stats_value if (stats_value := lead_qs.filter(status=LeadStatus.QUALIFIED).count()) is not None else 0},
        {"label": _("Converted"), "value": lead_qs.filter(status=LeadStatus.CONVERTED).count()},
        {"label": _("Lost"), "value": lead_qs.filter(status=LeadStatus.LOST).count()},
    ]
    max_leads = max([item["value"] for item in lead_pipeline] + [1])
    for item in lead_pipeline:
        item["width"] = round((item["value"] / max_leads) * 100, 2)
    cash_flow = []
    for index in range(7):
        day = today - timedelta(days=6 - index)
        money_in_day = sum((entry.amount for entry in recent_entries if entry.transaction_date == day and entry.direction == "in"), Decimal("0"))
        money_out_day = sum((entry.amount for entry in recent_entries if entry.transaction_date == day and entry.direction == "out"), Decimal("0"))
        cash_flow.append({"date": day, "in": money_in_day, "out": money_out_day, "label": date_format(day, "D")})
    max_cash = max([item["in"] for item in cash_flow] + [item["out"] for item in cash_flow] + [Decimal("1")])
    for item in cash_flow:
        item["in_height"] = round((item["in"] / max_cash) * 100, 2)
        item["out_height"] = round((item["out"] / max_cash) * 100, 2)
    recent_sales = list(sale_qs.select_related("customer", "vehicle").order_by("-created_at")[:5])
    recent_sale_payments = sale_payment_summaries(recent_sales) if request.user.company_id is not None else {}
    recent_sales_rows = [
        {"sale": sale, "payment": recent_sale_payments.get(sale.pk)}
        for sale in recent_sales
    ]
    outstanding_total = sum(
        (summary.get("outstanding", Decimal("0")) for summary in recent_sale_payments.values()),
        Decimal("0"),
    )
    negative_balances = sum(1 for total in cash_position.values() if total < 0)
    try:
        from apps.financing.models import AgreementStatus, Installment

        installment_qs = Installment.objects if request.user.company_id is not None else Installment.all_objects
        due_installments = installment_qs.filter(agreement__status=AgreementStatus.ACTIVE, due_date__lte=today).count()
    except Exception:
        due_installments = 0
    stats = {
        # Inventory state lives on VehicleStock (§8); Vehicle.status is deprecated.
        "vehicles_in_stock": stock_qs.filter(status=StockStatus.AVAILABLE).count(),
        "reserved_vehicles": stock_qs.filter(status=StockStatus.RESERVED).count(),
        "sold_pending_delivery": stock_qs.filter(status=StockStatus.SOLD).count(),
        "open_leads": lead_qs.filter(
            status__in=[LeadStatus.NEW, LeadStatus.CONTACTED, LeadStatus.QUALIFIED]
        ).count(),
        "qualified_leads": lead_qs.filter(status=LeadStatus.QUALIFIED).count(),
        "active_reservations": reservation_qs.filter(status=ReservationStatus.ACTIVE).count(),
        "active_sales": sale_qs.filter(status=SaleStatus.DRAFT).count(),
        "completed_sales": sale_qs.filter(status=SaleStatus.COMPLETED).count(),
        "customers": customer_qs.count(),
    }
    revenue_total = sales_by_currency[0]["total"] if sales_by_currency else Decimal("0")
    context = {
        "stats": stats,
        "inventory_statuses": {
            "available": stats["vehicles_in_stock"],
            "reserved": stats["reserved_vehicles"],
            "sold_pending_delivery": stats["sold_pending_delivery"],
        },
        "cash_position": cash_position,
        "money_in": money_in_total,
        "money_out": money_out_total,
        "recent_leads": lead_qs.select_related("assigned_to", "customer").order_by("-created_at")[:5],
        "recent_sales": recent_sales,
        "recent_sales_rows": recent_sales_rows,
        "recent_sale_payments": recent_sale_payments,
        "dashboard_currency": primary_currency,
        "dashboard_revenue": revenue_total,
        "dashboard_outstanding": outstanding_total,
        "sales_trend": sales_trend,
        "sales_trend_points": " ".join(revenue_points),
        "sales_count_points": " ".join(sales_count_points),
        "sales_trend_area_points": revenue_area_points,
        "inventory_mix": inventory_mix,
        "inventory_total": inventory_total,
        "lead_pipeline": lead_pipeline,
        "cash_flow": cash_flow,
        "attention_items": [
            {"label": _("Sold vehicles not delivered"), "help": _("Follow up with inventory and delivery."), "value": stats["sold_pending_delivery"], "tone": "amber"},
            {"label": _("Negative cash balances"), "help": _("Review bank and cashbox balances."), "value": negative_balances, "tone": "red"},
            {"label": _("Due installments"), "help": _("Review active financing schedules."), "value": due_installments, "tone": "violet"},
            {"label": _("Qualified leads"), "help": _("Prioritize hot opportunities."), "value": stats["qualified_leads"], "tone": "brand"},
        ],
        # Super Admin only: platform-wide tenant and user totals (§8.1).
        "platform": None,
    }
    if request.user.company_id is None:
        from apps.accounts.models import User
        from apps.organizations.models import Organization

        context["platform"] = {
            "companies": Organization.objects.count(),
            "users": User.objects.count(),
        }
    return render(request, "accounts/dashboard.html", context)


def admin_dashboard_callback(request, context):
    """Unfold admin index enrichment (UNFOLD["DASHBOARD_CALLBACK"]): platform
    KPI cards on the Super Admin home screen. Runs inside /admin/ only.
    Cards link to the models registered in Django Admin (§8.1)."""
    from apps.accounts.models import Role, User
    from apps.branches.models import Branch
    from apps.organizations.models import Organization

    context["navigation"] = [
        {
            "title": str(Organization.objects.count()),
            "link": reverse("admin:organizations_organization_changelist"),
            "subtitle": "Companies",
        },
        {
            "title": str(Branch.objects.count()),
            "link": reverse("admin:branches_branch_changelist"),
            "subtitle": "Branches",
        },
        {
            "title": str(User.objects.count()),
            "link": reverse("admin:accounts_user_changelist"),
            "subtitle": "Users",
        },
        {
            "title": str(Role.objects.count()),
            "link": reverse("admin:accounts_role_changelist"),
            "subtitle": "Roles",
        },
    ]
    return context


@require_POST
def set_language(request):
    """Language switcher (§11.2): stores the choice in the language cookie
    (what LocaleMiddleware reads), the session, and the user's
    preferred_language, then reloads the same page."""
    language = request.POST.get("language", "")
    response = redirect(request.META.get("HTTP_REFERER") or "/")
    if language in {code for code, _name in settings.LANGUAGES}:
        response = _language_cookie_response(response, language)
        if hasattr(request, "session"):
            request.session[LANGUAGE_SESSION_KEY] = language
        if request.user.is_authenticated:
            user = request.user
            if user.preferred_language != language:
                user.preferred_language = language
                user.save(update_fields=["preferred_language"])
    return response
