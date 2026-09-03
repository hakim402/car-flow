"""Import workflow: purchase type, shipment tracking, status chain, receiving
(agent.md §10 Step 5). Covers orders that bring vehicles in from abroad."""
import datetime

import pytest
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.branches.models import Branch
from apps.core.testing import SupplierFactory, UserFactory, VehicleFactory
from apps.inventory.models import VehicleStock
from apps.purchases.models import (
    CostType,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseStatus,
    PurchaseType,
    VehicleCostLine,
)


@pytest.fixture
def purchase_user(db):
    """Company user holding the purchase permissions the views check."""
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in ("purchases.view", "purchases.add", "purchases.change")
    ]
    role, _ = Role.objects.get_or_create(
        key="purchase_workflow_test", defaults={"name": "Purchase workflow test"}
    )
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def import_order(purchase_user):
    supplier = SupplierFactory(
        company=purchase_user.company, supplier_type="overseas_dealer", country="US"
    )
    return PurchaseOrder.all_objects.create(
        company=purchase_user.company,
        supplier=supplier,
        reference="IMP-001",
        purchase_type=PurchaseType.IMPORT,
        origin_country="US",
        incoterms="FOB",
        shipping_method="container",
        bill_of_lading_no="BL-123",
        container_no="CNTR-456",
        order_date=datetime.date(2026, 8, 1),
        eta=datetime.date(2026, 9, 15),
    )


@pytest.mark.django_db
def test_advance_walks_import_statuses(client, purchase_user, import_order):
    client.force_login(purchase_user)

    for expected in ("ordered", "shipped", "customs"):
        response = client.post(
            reverse("purchases:advance", args=[import_order.pk])
        )
        assert response.status_code == 302
        import_order = PurchaseOrder.all_objects.get(pk=import_order.pk)
        assert import_order.status == expected

    # Customs is the last advance step — receiving is a separate action.
    response = client.post(reverse("purchases:advance", args=[import_order.pk]))
    import_order = PurchaseOrder.all_objects.get(pk=import_order.pk)
    assert import_order.status == PurchaseStatus.CUSTOMS


@pytest.mark.django_db
def test_domestic_order_only_confirms_then_stops(client, purchase_user):
    supplier = SupplierFactory(company=purchase_user.company)
    order = PurchaseOrder.all_objects.create(
        company=purchase_user.company,
        supplier=supplier,
        order_date=datetime.date(2026, 8, 1),
    )
    client.force_login(purchase_user)

    client.post(reverse("purchases:advance", args=[order.pk]))
    order = PurchaseOrder.all_objects.get(pk=order.pk)
    assert order.status == PurchaseStatus.ORDERED

    # No transit/customs steps for domestic purchases.
    client.post(reverse("purchases:advance", args=[order.pk]))
    order = PurchaseOrder.all_objects.get(pk=order.pk)
    assert order.status == PurchaseStatus.ORDERED


@pytest.mark.django_db
def test_receive_import_order_records_cost_and_stock(client, purchase_user, import_order):
    branch = Branch.objects.create(company=purchase_user.company, name="HQ")
    import_order.branch = branch
    # Imported vehicles can only enter stock after the shipment reaches
    # customs; receiving a draft/ordered shipment is a workflow violation.
    import_order.status = PurchaseStatus.CUSTOMS
    import_order.save()
    vehicle = VehicleFactory(company=purchase_user.company)
    PurchaseOrderLine.objects.create(
        order=import_order,
        vehicle=vehicle,
        description="Toyota Corolla 2022",
        amount="15000.00",
        currency="USD",
    )
    client.force_login(purchase_user)

    response = client.post(reverse("purchases:receive", args=[import_order.pk]))

    assert response.status_code == 302
    import_order = PurchaseOrder.all_objects.get(pk=import_order.pk)
    assert import_order.status == PurchaseStatus.RECEIVED
    cost = VehicleCostLine.all_objects.get(vehicle=vehicle, cost_type=CostType.PURCHASE)
    assert cost.currency == "USD"
    assert VehicleStock.all_objects.filter(vehicle=vehicle, branch=branch).exists()


@pytest.mark.django_db
def test_import_order_requires_origin_country(client, purchase_user):
    supplier = SupplierFactory(company=purchase_user.company)
    client.force_login(purchase_user)

    base = {
        "reference": "IMP-002",
        "supplier": supplier.pk,
        "order_date": "2026-08-01",
        "purchase_type": PurchaseType.IMPORT,
    }
    response = client.post(reverse("purchases:create"), base)
    assert response.status_code == 200  # re-rendered with form errors
    assert not PurchaseOrder.all_objects.filter(reference="IMP-002").exists()

    response = client.post(reverse("purchases:create"), {**base, "origin_country": "AE"})
    assert response.status_code == 302
    order = PurchaseOrder.all_objects.get(reference="IMP-002")
    assert order.is_import
    assert order.origin_country == "AE"


@pytest.mark.django_db
def test_list_shows_import_badge_and_filters(client, purchase_user, import_order):
    client.force_login(purchase_user)

    response = client.get(reverse("purchases:list"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "IMP-001" in content
    assert "United States" in content  # origin on the import badge

    response = client.get(reverse("purchases:list") + "?status=draft")
    assert "IMP-001" in response.content.decode()
    response = client.get(reverse("purchases:list") + "?status=received")
    assert "IMP-001" not in response.content.decode()
