from decimal import Decimal

import pytest
from django.conf import settings
from django.urls import reverse

from apps.core.tenancy import company_scope
from apps.core.testing import SaleFactory, UserFactory
from apps.payments.services import record_payment
from apps.sales.models import SaleStatus


@pytest.mark.django_db
def test_receivables_route_shows_small_remaining_customer_balance(client):
    sale = SaleFactory(
        agreed_amount=Decimal("100.00"),
        currency="USD",
        status=SaleStatus.COMPLETED,
    )
    user = UserFactory(company=sale.company)
    with company_scope(sale.company):
        record_payment(sale, Decimal("98.00"), "USD", user=user)
    client.force_login(user)

    response = client.get(reverse("accounting:receivables"))

    assert response.status_code == 200
    html = response.content.decode()
    assert sale.customer.full_name in html
    assert "2.00 USD" in html
    assert reverse("financing:create") + f"?sale={sale.pk}" in html


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("language", "heading"),
    [
        ("prs", "مانده حساب مشتریان"),
        ("ps", "د پېرودونکو پاتې حسابونه"),
    ],
)
def test_receivables_page_is_translated(client, language, heading):
    user = UserFactory()
    client.force_login(user)
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
    response = client.get(reverse("accounting:receivables"))

    assert response.status_code == 200
    assert heading in response.content.decode()
