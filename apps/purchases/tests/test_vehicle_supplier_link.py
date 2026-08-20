"""Car ↔ supplier connection: every vehicle shows which supplier it was
bought from (via its purchase-order lines), and every supplier lists the
cars bought from it — with full purchase details on both sides."""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.core.testing import SupplierFactory, UserFactory, VehicleFactory
from apps.purchases.models import PurchaseOrder, PurchaseOrderLine, PurchaseStatus


@pytest.fixture
def company_user(db):
    """Company user holding the view permissions the pages check."""
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in ("vehicles.view", "suppliers.view")
    ]
    role, _ = Role.objects.get_or_create(
        key="vehicle_supplier_link_test",
        defaults={"name": "Vehicle supplier link test"},
    )
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def bought_car(company_user):
    """A vehicle linked to a supplier through a purchase-order line."""
    supplier = SupplierFactory(company=company_user.company, name="Kabul Motors")
    vehicle = VehicleFactory(company=company_user.company, vin="LINKVIN0000000001")
    order = PurchaseOrder.all_objects.create(
        company=company_user.company,
        supplier=supplier,
        reference="BUY-001",
        status=PurchaseStatus.RECEIVED,
        order_date=datetime.date(2026, 5, 10),
    )
    line = PurchaseOrderLine.objects.create(
        order=order,
        vehicle=vehicle,
        description="Car purchase",
        amount=Decimal("12500.00"),
        currency="USD",
    )
    return vehicle, supplier, order, line


@pytest.mark.django_db
def test_vehicle_detail_shows_supplier_and_purchase_details(
    client, company_user, bought_car
):
    vehicle, supplier, order, line = bought_car
    client.force_login(company_user)

    response = client.get(vehicle.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert supplier.name in content  # "Bought from" + purchase table
    assert supplier.get_absolute_url() in content
    assert "BUY-001" in content  # purchase order reference
    assert order.get_absolute_url() in content
    assert "12500.00" in content  # amount paid for this car
    assert order.get_status_display() in content


@pytest.mark.django_db
def test_vehicle_card_shows_source_supplier(client, company_user, bought_car):
    vehicle, supplier, _, _ = bought_car
    client.force_login(company_user)

    response = client.get(reverse("vehicles:list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert vehicle.vin in content
    assert supplier.name in content  # "From: Kabul Motors" on the card


@pytest.mark.django_db
def test_supplier_detail_lists_cars_bought(client, company_user, bought_car):
    vehicle, supplier, order, line = bought_car
    client.force_login(company_user)

    response = client.get(supplier.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert str(vehicle) in content  # "2020 Toyota Corolla (VIN)"
    assert vehicle.get_absolute_url() in content
    assert vehicle.vin in content
    assert "BUY-001" in content
    assert "12500.00" in content
