"""Supplier cards and detail page with order history (agent.md §10 Step 5).

Suppliers are the import side of the business — cards expose country/type,
and the detail page lists every purchase order placed with them."""
import datetime

import pytest
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.core.testing import SupplierFactory, UserFactory
from apps.purchases.models import PurchaseOrder, PurchaseType


@pytest.fixture
def supplier_user(db):
    """Company user holding the supplier permissions the views check."""
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in ("suppliers.view", "suppliers.change", "purchases.view")
    ]
    role, _ = Role.objects.get_or_create(
        key="supplier_cards_test", defaults={"name": "Supplier cards test"}
    )
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def overseas_supplier(supplier_user):
    return SupplierFactory(
        company=supplier_user.company,
        name="Dubai Motors LLC",
        supplier_type="overseas_dealer",
        country="AE",
        phone="+971500000000",
    )


@pytest.mark.django_db
def test_list_renders_cards_with_country_and_type(client, supplier_user, overseas_supplier):
    client.force_login(supplier_user)

    response = client.get(reverse("suppliers:list"))

    assert response.status_code == 200
    content = response.content.decode()
    # Card, not table: name + type + country + link to the detail page.
    assert "<table" not in content
    assert overseas_supplier.name in content
    assert "Overseas dealer" in content
    assert "United Arab Emirates" in content
    assert overseas_supplier.get_absolute_url() in content


@pytest.mark.django_db
def test_detail_shows_profile_and_order_history(client, supplier_user, overseas_supplier):
    order = PurchaseOrder.all_objects.create(
        company=supplier_user.company,
        supplier=overseas_supplier,
        reference="IMP-777",
        purchase_type=PurchaseType.IMPORT,
        origin_country="AE",
        order_date=datetime.date(2026, 7, 1),
    )
    client.force_login(supplier_user)

    response = client.get(overseas_supplier.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert overseas_supplier.name in content
    assert "United Arab Emirates" in content
    assert order.get_absolute_url() in content
    assert "IMP-777" in content


@pytest.mark.django_db
def test_foreign_company_supplier_404s(client, supplier_user):
    foreign_supplier = SupplierFactory()  # its own (different) company
    client.force_login(supplier_user)

    response = client.get(
        reverse("suppliers:detail", args=[foreign_supplier.pk])
    )

    assert response.status_code == 404
