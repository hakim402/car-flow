from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.tenancy import company_scope
from apps.core.testing import CustomerFactory, OrganizationFactory, UserFactory, VehicleFactory
from apps.sales.models import Lead, LeadStatus, Reservation


@pytest.fixture
def sales_user(db):
    return UserFactory(email="sales-workspace@example.com")


@pytest.mark.django_db
def test_lead_workspace_searches_and_paginates_within_tenant(client, sales_user):
    with company_scope(sales_user.company):
        for index in range(13):
            Lead.objects.create(
                company=sales_user.company,
                name=f"Prospect {index:02d}",
                phone=f"+9370000{index:04d}",
                status=LeadStatus.NEW,
                created_by=sales_user,
            )
    foreign_company = OrganizationFactory()
    with company_scope(foreign_company):
        Lead.objects.create(company=foreign_company, name="Foreign Prospect")

    client.force_login(sales_user)
    response = client.get(reverse("sales:lead_list"), {"page": 2})

    assert response.status_code == 200
    assert response.context["page_obj"].paginator.count == 13
    assert len(response.context["leads"]) == 1
    assert "Foreign Prospect" not in response.content.decode()

    filtered = client.get(reverse("sales:lead_list"), {"q": "Prospect 12"})
    assert filtered.status_code == 200
    assert filtered.context["page_obj"].paginator.count == 1
    assert "Prospect 12" in filtered.content.decode()


@pytest.mark.django_db
def test_reservation_has_inspectable_detail_with_ledger_balance_actions(client, sales_user):
    customer = CustomerFactory(company=sales_user.company)
    vehicle = VehicleFactory(company=sales_user.company)
    with company_scope(sales_user.company):
        reservation = Reservation.objects.create(
            company=sales_user.company,
            customer=customer,
            vehicle=vehicle,
            deposit_amount=Decimal("500.00"),
            currency="USD",
            created_by=sales_user,
        )

    client.force_login(sales_user)
    response = client.get(reservation.get_absolute_url())

    assert response.status_code == 200
    html = response.content.decode()
    assert "RSV-" in html
    assert "500.00" in html
    assert reverse("payments:create") in html
    assert f"reservation={reservation.pk}" in html
