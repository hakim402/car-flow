from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import User
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
