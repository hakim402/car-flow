from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core.tenancy import company_scope
from apps.core.testing import CustomerFactory, OrganizationFactory, UserFactory, VehicleFactory
from apps.payments.models import EntryType, FinancialAccount, LedgerEntry
from apps.sales.models import Lead, LeadStatus


@pytest.mark.django_db
def test_company_dashboard_shows_operations_metrics_without_platform_admin_cards():
    company = OrganizationFactory(name="Auto North")
    user = UserFactory(company=company, email="ops@example.com")

    with company_scope(company):
        Lead.objects.create(
            company=company,
            name="Bashir Noor",
            phone="+93712345678",
            status=LeadStatus.NEW,
            branch=None,
            assigned_to=user,
            created_by=user,
        )
        customer = CustomerFactory(company=company)
        vehicle = VehicleFactory(company=company)
        account = FinancialAccount.objects.create(
            company=company,
            name="Main Cash",
            account_type=FinancialAccount.AccountType.CASH,
            currency="USD",
            active=True,
        )
        LedgerEntry.objects.create(
            company=company,
            type=EntryType.CUSTOMER_PAYMENT,
            amount=Decimal("1250.00"),
            currency="USD",
            account=account,
            customer=customer,
            sale=None,
            description="Deposit received",
            reference="DEP-001",
            created_by=user,
        )

    client = pytest.importorskip("django.test").Client()
    client.force_login(user)

    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert "Open leads" in response.content.decode()
    assert "Cash position" in response.content.decode()
    assert "Operations snapshot" in response.content.decode()
    assert "Companies" not in response.content.decode()
    assert "Users" not in response.content.decode()


@pytest.mark.django_db
def test_company_dashboard_exposes_finance_setup_links():
    company = OrganizationFactory(name="Fresh Auto")
    user = UserFactory(company=company, email="setup@example.com")

    client = pytest.importorskip("django.test").Client()
    client.force_login(user)

    response = client.get(reverse("home"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Financial accounts" in html
    assert "Expense categories" in html
    assert reverse("payments:account_list") in html
    assert reverse("expenses:category_list") in html


@pytest.mark.django_db
def test_super_admin_role_has_full_permission_access_and_company_dashboard_hides_admin_cards():
    role = Role.objects.get_or_create(key="super_admin", defaults={"name": "Super Admin", "system": True})[0]
    user = UserFactory(email="superrole@example.com", company=None)
    user.roles.add(role)

    assert user.is_super_admin
    assert user.has_permission("sales.view")
    assert user.has_permission("inventory.view")
    assert user.has_permission("payments.view")

    client = pytest.importorskip("django.test").Client()
    client.force_login(user)
    response = client.get(reverse("home"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Companies" in html
    assert "Users" in html
    assert "Open leads" not in html


@pytest.mark.django_db
def test_role_matrix_limits_sidebar_links_to_allowed_sections():
    company = OrganizationFactory(name="Role Matrix Co")

    sales_user = UserFactory(company=company, email="sales-role@example.com")
    sales_user.roles.add(Role.objects.get(key="sales"))

    inventory_user = UserFactory(company=company, email="inventory-role@example.com")
    inventory_user.roles.add(Role.objects.get(key="inventory"))

    accountant_user = UserFactory(company=company, email="accountant-role@example.com")
    accountant_user.roles.add(Role.objects.get(key="accountant"))

    client = pytest.importorskip("django.test").Client()

    client.force_login(sales_user)
    sales_response = client.get(reverse("home"))
    sales_html = sales_response.content.decode()
    assert reverse("sales:lead_list") in sales_html
    assert reverse("customers:list") in sales_html
    assert reverse("inventory:list") not in sales_html
    assert reverse("payments:list") not in sales_html
    assert reverse("expenses:list") not in sales_html
    assert reverse("purchases:list") not in sales_html

    client.force_login(inventory_user)
    inventory_response = client.get(reverse("home"))
    inventory_html = inventory_response.content.decode()
    assert reverse("inventory:list") in inventory_html
    assert reverse("vehicles:list") in inventory_html
    assert reverse("sales:lead_list") not in inventory_html
    assert reverse("payments:list") not in inventory_html

    client.force_login(accountant_user)
    accountant_response = client.get(reverse("home"))
    accountant_html = accountant_response.content.decode()
    assert reverse("payments:list") in accountant_html
    assert reverse("expenses:list") in accountant_html
    assert reverse("accounting:summary") in accountant_html
    assert reverse("inventory:list") not in accountant_html
