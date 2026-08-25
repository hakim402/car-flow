"""Inventory views: permission gates, stock list/detail, guarded status
changes, internal moves, branch transfers and location management. All
mutations must land through the service layer — the views never save stock
rows directly (README §8.3)."""
import pytest
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.branches.models import Branch
from apps.core.tenancy import company_scope
from apps.core.testing import UserFactory, VehicleFactory
from apps.inventory.models import (
    InventoryLocation,
    InventoryMovement,
    MovementType,
    StockStatus,
    VehicleStock,
)
from apps.inventory.services import receive_vehicle


@pytest.fixture
def inventory_user(db):
    """Company user holding every inventory permission the views check."""
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in (
            "inventory.view",
            "inventory.add",
            "inventory.change",
            "inventory.move",
            "inventory.transfer",
        )
    ]
    role, _ = Role.objects.get_or_create(
        key="inventory_test", defaults={"name": "Inventory test"}
    )
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def stock(inventory_user):
    branch = Branch.objects.create(company=inventory_user.company, name="HQ")
    vehicle = VehicleFactory(company=inventory_user.company)
    with company_scope(inventory_user.company):
        return receive_vehicle(vehicle, branch)


@pytest.mark.django_db
def test_stock_list_requires_permission(client):
    client.force_login(UserFactory())  # no roles at all
    response = client.get(reverse("inventory:list"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_stock_list_shows_vehicle_and_status(client, inventory_user, stock):
    client.force_login(inventory_user)
    response = client.get(reverse("inventory:list"))
    assert response.status_code == 200
    content = response.content.decode()
    assert stock.vehicle.vin in content
    assert "HQ" in content


@pytest.mark.django_db
def test_stock_list_is_branch_scoped(client, inventory_user, stock):
    other_branch = Branch.objects.create(company=inventory_user.company, name="South")
    other_vehicle = VehicleFactory(company=inventory_user.company)
    with company_scope(inventory_user.company):
        receive_vehicle(other_vehicle, other_branch)

    inventory_user.branch = other_branch
    inventory_user.save(update_fields=["branch"])
    client.force_login(inventory_user)

    response = client.get(reverse("inventory:list"))
    content = response.content.decode()
    assert other_vehicle.vin in content
    assert stock.vehicle.vin not in content


@pytest.mark.django_db
def test_stock_detail_shows_movement_history(client, inventory_user, stock):
    client.force_login(inventory_user)
    response = client.get(reverse("inventory:stock_detail", args=[stock.pk]))
    assert response.status_code == 200
    content = response.content.decode()
    assert stock.vehicle.vin in content
    assert "Receive" in content  # the RECEIVE movement is listed
    assert stock.get_status_display() in content


@pytest.mark.django_db
def test_update_status_applies_allowed_transition(client, inventory_user, stock):
    client.force_login(inventory_user)
    response = client.post(
        reverse("inventory:update_status", args=[stock.pk]),
        {"status": StockStatus.INSPECTION},
    )
    assert response.status_code == 302
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    assert stock.status == StockStatus.INSPECTION
    assert InventoryMovement.all_objects.filter(
        vehicle=stock.vehicle, movement_type=MovementType.ADJUSTMENT
    ).exists()


@pytest.mark.django_db
def test_update_status_rejects_invalid_transition(client, inventory_user, stock):
    client.force_login(inventory_user)
    response = client.post(
        reverse("inventory:update_status", args=[stock.pk]),
        {"status": StockStatus.SOLD},  # RECEIVED -> SOLD is illegal
    )
    assert response.status_code == 302
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    assert stock.status == StockStatus.RECEIVED  # unchanged
    assert InventoryMovement.all_objects.filter(
        vehicle=stock.vehicle, movement_type=MovementType.ADJUSTMENT
    ).count() == 0


@pytest.mark.django_db
def test_move_view(client, inventory_user, stock):
    location = InventoryLocation.all_objects.create(
        company=inventory_user.company, branch=stock.branch, name="Workshop"
    )
    client.force_login(inventory_user)
    response = client.post(
        reverse("inventory:move", args=[stock.pk]),
        {"location": location.pk, "notes": "Engine work"},
    )
    assert response.status_code == 302
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    assert stock.location == location
    movement = InventoryMovement.all_objects.get(
        vehicle=stock.vehicle, movement_type=MovementType.MOVE
    )
    assert movement.to_location == location
    assert movement.notes == "Engine work"


@pytest.mark.django_db
def test_transfer_view(client, inventory_user, stock):
    other_branch = Branch.objects.create(company=inventory_user.company, name="South")
    client.force_login(inventory_user)
    response = client.post(
        reverse("inventory:transfer", args=[stock.pk]),
        {"branch": other_branch.pk, "notes": "Showroom swap"},
    )
    assert response.status_code == 302
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    assert stock.branch == other_branch
    movement = InventoryMovement.all_objects.get(
        vehicle=stock.vehicle, movement_type=MovementType.TRANSFER
    )
    assert movement.to_branch == other_branch


@pytest.mark.django_db
def test_transfer_view_rejects_foreign_branch(client, inventory_user, stock):
    stranger = Branch.objects.create(company=UserFactory().company, name="Foreign")
    client.force_login(inventory_user)
    response = client.post(
        reverse("inventory:transfer", args=[stock.pk]), {"branch": stranger.pk}
    )
    assert response.status_code == 302
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    assert stock.branch.name == "HQ"  # unchanged
    assert InventoryMovement.all_objects.filter(
        vehicle=stock.vehicle, movement_type=MovementType.TRANSFER
    ).count() == 0


@pytest.mark.django_db
def test_location_create_and_toggle(client, inventory_user, stock):
    client.force_login(inventory_user)
    response = client.post(
        reverse("inventory:location_create"),
        {"branch": stock.branch.pk, "name": "Showroom A", "type": "showroom", "code": "SH-A"},
    )
    assert response.status_code == 302
    location = InventoryLocation.all_objects.get(code="SH-A")
    assert location.active

    response = client.post(reverse("inventory:location_toggle", args=[location.pk]))
    assert response.status_code == 302
    location = InventoryLocation.all_objects.get(pk=location.pk)
    assert not location.active
