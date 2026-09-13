"""Project URL configuration.

App URLs are mounted here as each app ships (agent.md §10 build order).
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import dashboard
from apps.communications.webhooks import meta_webhook

# Load app-specific Unfold registrations first, then fill in every remaining
# model for the emergency console.
admin.autodiscover()
import config.admin  # noqa: F401,E402


def _superadmin_permission(request):
    return bool(request.user.is_active and request.user.is_superuser)


# Stronger than Django's normal is_staff gate; there is no /admin/ fallback.
admin.site.has_permission = _superadmin_permission

urlpatterns = [
    path("", dashboard, name="home"),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("vehicles/", include("apps.vehicles.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("suppliers/", include("apps.suppliers.urls")),
    path("purchases/", include("apps.purchases.urls")),
    path("customers/", include("apps.customers.urls")),
    path("sales/", include("apps.sales.urls")),
    path("payments/", include("apps.payments.urls")),
    path("financing/", include("apps.financing.urls")),
    path("expenses/", include("apps.expenses.urls")),
    path("accounting/", include("apps.accounting.urls")),
    path("conversations/", include("apps.communications.urls")),
    path("documents/", include("apps.documents.urls")),
    # Provider webhooks (§7.3) — one inbound endpoint per provider family.
    path("webhooks/meta/", meta_webhook, name="webhook_meta"),
    path(f"{settings.SUPERADMIN_URL}/", admin.site.urls),
]

if settings.DEBUG:
    # Local media serving (dev only; Nginx serves media in production).
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
