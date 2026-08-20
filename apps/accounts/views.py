from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
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


class CarFlowLoginView(auth_views.LoginView):
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
    totals through the same unfiltered manager (§5)."""
    # Imports stay local: this view lives in the auth app and must not drag
    # the business models into its module-import graph at startup.
    from apps.customers.models import Customer
    from apps.sales.models import Lead, LeadStatus, Sale, SaleStatus
    from apps.vehicles.models import Vehicle, VehicleStatus

    stats = {
        "vehicles_in_stock": Vehicle.objects.filter(
            status=VehicleStatus.IN_STOCK
        ).count(),
        "open_leads": Lead.objects.filter(
            status__in=[LeadStatus.NEW, LeadStatus.CONTACTED, LeadStatus.QUALIFIED]
        ).count(),
        "active_sales": Sale.objects.filter(status=SaleStatus.DRAFT).count(),
        "customers": Customer.objects.count(),
    }
    context = {
        "stats": stats,
        "recent_sales": Sale.objects.select_related("customer", "vehicle")
        .order_by("-created_at")[:5],
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
