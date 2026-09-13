from decimal import Decimal

import pytest
from django.conf import settings
from django.urls import NoReverseMatch, reverse

from apps.accounts.models import Role
from apps.accounting.report_access import can_deliver_report, can_view_report
from apps.accounting.reporting import REPORTS
from apps.core.testing import SaleFactory, UserFactory
from apps.sales.models import SaleStatus


@pytest.mark.django_db
def test_only_business_activity_report_workspace_renders(client):
    user = UserFactory()
    user.roles.add(Role.objects.get(key="org_admin"))
    SaleFactory(company=user.company, agreed_amount=Decimal("12500.00"), status=SaleStatus.COMPLETED)
    client.force_login(user)
    response = client.get(reverse("accounting:report", kwargs={"key": "activity"}))
    assert response.status_code == 200
    html = response.content.decode()
    assert response.context["report_data"]["key"] == "activity"
    assert "reports.css" in html
    assert "report-workspace-activity" in html
    assert "Audit table" in html
    assert "Audit activity analytics" not in html
    assert "Changes over time" not in html
    assert "Recorded changes" not in html
    assert "Created records" not in html
    assert "Active staff" not in html
    assert "Updated records" not in html
    assert "report-summary-analytics" not in html
    assert "Export report" not in html
    assert "Share snapshot" not in html
    assert "Delivery history" not in html
    assert "Saved views" not in html
    assert "Compare previous period" not in html
    assert "Browse reports" not in html
    assert "Report center" not in html
    assert "Financial Reports" not in html
    assert "Business Reports" not in html


@pytest.mark.django_db
@pytest.mark.parametrize("url", [
    "/accounting/",
    "/accounting/cash-position/",
    "/accounting/expenses/",
    "/accounting/profitability/",
    "/accounting/reports/summary/",
    "/accounting/reports/cash-position/",
    "/accounting/reports/expenses/",
    "/accounting/reports/profitability/",
    "/accounting/reports/financing/",
    "/accounting/reports/sales/",
    "/accounting/reports/stock/",
    "/accounting/reports/purchases/",
    "/accounting/reports/contacts/",
    "/accounting/receivables/",
    "/accounting/payables/",
    "/accounting/reports/communications/",
    "/accounting/reports/documents/",
    "/accounting/reports/activity/export/",
    "/accounting/reports/activity/share/",
    "/accounting/delivery/",
    "/accounting/exports/1/",
    "/accounting/exports/1/download/",
    "/accounting/shared/example-token/",
])
def test_removed_report_routes_return_404(client, url):
    user = UserFactory()
    user.roles.add(Role.objects.get(key="org_admin"))
    client.force_login(user)
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_removed_named_report_routes_are_gone():
    for name in (
        "summary", "cash_position", "expense_analysis", "profitability",
        "export_create", "share_create", "delivery_history", "export_status",
        "export_download", "share_revoke", "shared_report",
    ):
        with pytest.raises(NoReverseMatch):
            reverse(f"accounting:{name}")


@pytest.mark.django_db
def test_sidebar_uses_direct_business_activity_link_only(client):
    user = UserFactory()
    user.roles.add(Role.objects.get(key="org_admin"))
    client.force_login(user)
    response = client.get(reverse("accounting:report", kwargs={"key": "activity"}))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Business Activity" in html
    assert f'href="{reverse("accounting:report", kwargs={"key": "activity"})}"' in html
    assert "Financial Reports" not in html
    assert "Business Reports" not in html
    assert "Report Overview" not in html
    assert "Cash Position" not in html
    assert "Expense Analysis" not in html
    assert "Vehicle Profitability" not in html
    assert "Financing and Collections" not in html
    assert "Sales and Pipeline" not in html
    assert "Inventory and Vehicles" not in html
    assert "Purchases and Imports" not in html
    assert "Customers and Partners" not in html


@pytest.mark.django_db
def test_invalid_activity_filters_render_validation_not_database_errors(client):
    user = UserFactory()
    user.roles.add(Role.objects.get(key="org_admin"))
    client.force_login(user)
    response = client.get(reverse("accounting:report", kwargs={"key": "activity"}), {"date_from": "not-a-date"})
    assert response.status_code == 400
    assert response.context["filter_form"].errors
    assert "can_export" not in response.context
    assert "can_share" not in response.context


@pytest.mark.django_db
def test_no_role_does_not_implicitly_authorize_activity_or_delivery():
    user = UserFactory()
    assert not can_view_report(user, "activity")
    assert not can_deliver_report(user, "activity", "export")
    assert not can_deliver_report(user, "activity", "share")
    assert set(REPORTS) == {"activity"}


@pytest.mark.django_db
@pytest.mark.parametrize("language,direction", [("en", "ltr"), ("prs", "rtl"), ("ps", "rtl")])
def test_activity_report_language_direction_and_translation(client, language, direction):
    user = UserFactory()
    user.roles.add(Role.objects.get(key="org_admin"))
    client.force_login(user)
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
    response = client.get(reverse("accounting:report", kwargs={"key": "activity"}))
    assert response.status_code == 200
    html = response.content.decode()
    assert f'dir="{direction}"' in html
    assert f'lang="{language}"' in html


@pytest.mark.django_db
def test_activity_report_requires_authenticated_company(client):
    url = reverse("accounting:report", kwargs={"key": "activity"})
    assert client.get(url).status_code == 302
    client.force_login(UserFactory(company=None, is_superuser=True))
    assert client.get(url).status_code == 403
