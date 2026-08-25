"""Inventory mutation service layer (README §8.3).

Every test asserts BOTH halves of the contract: the `VehicleStock` row
reflects the change AND an `InventoryMovement` row was appended to prove it.
Services are exercised under tenant scope because they use the fail-closed
tenant manager (§25.1)."""
import pytest
from django.core.exceptions import ValidationError

from apps.branches.models import Branch
from apps.core.tenancy import company_scope
from apps.core.testing import OrganizationFactory, UserFactory, VehicleFactory
from apps.inventory.models import (
    InventoryLocation,
    InventoryMovement,
    MovementType,
    StockStatus,
    VehicleStock,
)
from apps.inventory.services import (
    adjust_stock_status,
    deliver_stock,
    move_stock,
    receive_vehicle,
    release_stock,
    reserve_stock,
    return_stock,
    sell_stock,
    transfer_stock,
)


@pytest.fixture
def company(db):
    return OrganizationFactory()


@pytest.fixture
def branch(db, company):
    return Branch.objects.create(company=company, name="HQ")


@pytest.fixture
def other_branch(db, company):
    return Branch.objects.create(company=company, name="South")


@pytest.fixture
def vehicle(db, company):
    return VehicleFactory(company=company)


@pytest.fixture
def user(db, company):
    return UserFactory(company=company)


@pytest.fixture
def received(db, vehicle, branch):
    with company_scope(vehicle.company):
        return receive_vehicle(vehicle, branch)


def movements(vehicle, movement_type=None):
    queryset = InventoryMovement.all_objects.filter(vehicle=vehicle)
    if movement_type is not None:
        queryset = queryset.filter(movement_type=movement_type)
    return queryset


def test_receive_creates_stock_and_receive_movement(vehicle, branch, user):
    with company_scope(vehicle.company):
        stock = receive_vehicle(vehicle, branch, user=user, notes="Unloaded")
    assert stock.status == StockStatus.RECEIVED
    assert stock.branch == branch
    movement = InventoryMovement.all_objects.get(vehicle=vehicle)
    assert movement.movement_type == MovementType.RECEIVE
    assert movement.to_branch == branch
    assert movement.performed_by == user
    assert movement.notes == "Unloaded"


def test_receive_is_idempotent(vehicle, branch):
    with company_scope(vehicle.company):
        first = receive_vehicle(vehicle, branch)
        second = receive_vehicle(vehicle, branch)
    assert first.pk == second.pk
    assert InventoryMovement.all_objects.filter(vehicle=vehicle).count() == 1


def test_receive_rejects_cross_company_branch(vehicle):
    stranger = Branch.objects.create(company=OrganizationFactory(), name="Elsewhere")
    with company_scope(vehicle.company):
        with pytest.raises(ValidationError):
            receive_vehicle(vehicle, stranger)
    assert not VehicleStock.all_objects.filter(vehicle=vehicle).exists()


def test_transfer_records_from_and_to_branch(received, vehicle, other_branch):
    from_branch = received.branch
    with company_scope(vehicle.company):
        transfer_stock(received, other_branch, notes="Relocating")
    received = VehicleStock.all_objects.get(pk=received.pk)
    assert received.branch == other_branch
    movement = movements(vehicle, MovementType.TRANSFER).get()
    assert movement.from_branch == from_branch
    assert movement.to_branch == other_branch
    assert movement.notes == "Relocating"


def test_transfer_noop_writes_no_movement(received, vehicle, branch):
    with company_scope(vehicle.company):
        transfer_stock(received, branch)
    assert movements(vehicle, MovementType.TRANSFER).count() == 0


def test_transfer_rejects_location_of_another_branch(received, vehicle, other_branch):
    # Location lives on the CURRENT branch while the transfer targets another
    # one — the combination is impossible and must be rejected.
    location = InventoryLocation.all_objects.create(
        company=vehicle.company, branch=received.branch, name="HQ yard"
    )
    with company_scope(vehicle.company):
        with pytest.raises(ValidationError):
            transfer_stock(received, other_branch, to_location=location)


def test_transfer_rejects_delivered_vehicle(received, vehicle, other_branch):
    with company_scope(vehicle.company):
        adjust_stock_status(received, StockStatus.AVAILABLE)
        sell_stock(vehicle)
        deliver_stock(vehicle)
        with pytest.raises(ValidationError):
            transfer_stock(received, other_branch)


def test_move_within_branch_records_locations(received, vehicle, branch):
    from_location = InventoryLocation.all_objects.create(
        company=vehicle.company, branch=branch, name="Showroom"
    )
    to_location = InventoryLocation.all_objects.create(
        company=vehicle.company, branch=branch, name="Workshop"
    )
    with company_scope(vehicle.company):
        move_stock(received, from_location)
        move_stock(received, to_location)
    movement = movements(vehicle, MovementType.MOVE).order_by("pk").last()
    assert movement.from_location == from_location
    assert movement.to_location == to_location
    received = VehicleStock.all_objects.get(pk=received.pk)
    assert received.location == to_location


def test_move_rejects_cross_branch_location(received, vehicle, other_branch):
    location = InventoryLocation.all_objects.create(
        company=vehicle.company, branch=other_branch, name="Other yard"
    )
    with company_scope(vehicle.company):
        with pytest.raises(ValidationError):
            move_stock(received, location)


def test_move_noop_writes_no_movement(received, vehicle, branch):
    location = InventoryLocation.all_objects.create(
        company=vehicle.company, branch=branch, name="Showroom"
    )
    with company_scope(vehicle.company):
        move_stock(received, location)
        move_stock(received, location)
    assert movements(vehicle, MovementType.MOVE).count() == 1


def test_lifecycle_progression_stamps_available_at(received, vehicle):
    with company_scope(vehicle.company):
        adjust_stock_status(received, StockStatus.INSPECTION)
        adjust_stock_status(received, StockStatus.PREPARATION)
        adjust_stock_status(received, StockStatus.AVAILABLE)
    stock = VehicleStock.all_objects.get(pk=received.pk)
    assert stock.status == StockStatus.AVAILABLE
    assert stock.available_at is not None
    assert movements(vehicle, MovementType.ADJUSTMENT).count() == 3


def test_invalid_transition_is_rejected(received, vehicle):
    with company_scope(vehicle.company):
        with pytest.raises(ValidationError):
            adjust_stock_status(received, StockStatus.SOLD)  # RECEIVED -> SOLD
    stock = VehicleStock.all_objects.get(pk=received.pk)
    assert stock.status == StockStatus.RECEIVED
    assert movements(vehicle, MovementType.ADJUSTMENT).count() == 0


def test_reserve_release_cycle(received, vehicle):
    with company_scope(vehicle.company):
        adjust_stock_status(received, StockStatus.AVAILABLE)
        reserve_stock(vehicle, notes="Held for Ali")
        stock = VehicleStock.all_objects.get(pk=received.pk)
        assert stock.status == StockStatus.RESERVED
        assert stock.reserved_at is not None
        release_stock(vehicle, notes="Cancelled")
        stock = VehicleStock.all_objects.get(pk=received.pk)
        assert stock.status == StockStatus.AVAILABLE
    assert movements(vehicle, MovementType.RESERVE).count() == 1
    assert movements(vehicle, MovementType.RELEASE).count() == 1


def test_reserve_requires_stock_row(vehicle):
    with company_scope(vehicle.company):
        with pytest.raises(ValidationError):
            reserve_stock(vehicle)


def test_sell_stamps_sold_at_and_is_idempotent(received, vehicle, user):
    with company_scope(vehicle.company):
        adjust_stock_status(received, StockStatus.AVAILABLE)
        sell_stock(vehicle, user=user, notes="Sale #7")
        stock = VehicleStock.all_objects.get(pk=received.pk)
        assert stock.status == StockStatus.SOLD
        assert stock.sold_at is not None
        # A second (e.g. raced) completion must not double-record.
        sell_stock(vehicle, user=user, notes="Sale #7 again")
    movement = movements(vehicle, MovementType.SALE).get()
    assert movement.performed_by == user
    assert movements(vehicle, MovementType.SALE).count() == 1


def test_deliver_after_sale_and_stock_row_survives(received, vehicle):
    with company_scope(vehicle.company):
        adjust_stock_status(received, StockStatus.AVAILABLE)
        sell_stock(vehicle)
        deliver_stock(vehicle)
    stock = VehicleStock.all_objects.get(pk=received.pk)
    assert stock.status == StockStatus.DELIVERED
    assert stock.delivered_at is not None
    # The row is historical evidence — never deleted on sale/delivery (§8.2).
    assert VehicleStock.all_objects.filter(vehicle=vehicle).count() == 1
    assert movements(vehicle, MovementType.DELIVERY).count() == 1


def test_deliver_requires_sold(received, vehicle):
    with company_scope(vehicle.company):
        with pytest.raises(ValidationError):
            deliver_stock(vehicle)  # RECEIVED -> DELIVERED is illegal


def test_return_brings_vehicle_back_and_can_reposition(received, vehicle, other_branch):
    with company_scope(vehicle.company):
        adjust_stock_status(received, StockStatus.AVAILABLE)
        sell_stock(vehicle)
        deliver_stock(vehicle)
        location = InventoryLocation.all_objects.create(
            company=vehicle.company, branch=other_branch, name="Return bay"
        )
        return_stock(vehicle, branch=other_branch, location=location)
    stock = VehicleStock.all_objects.get(pk=received.pk)
    assert stock.status == StockStatus.AVAILABLE
    assert stock.branch == other_branch
    assert stock.location == location
    assert movements(vehicle, MovementType.RETURN).count() == 1


def test_return_rejects_location_of_other_branch(received, vehicle, other_branch):
    with company_scope(vehicle.company):
        adjust_stock_status(received, StockStatus.AVAILABLE)
        sell_stock(vehicle)
        deliver_stock(vehicle)
        location = InventoryLocation.all_objects.create(
            company=vehicle.company, branch=received.branch, name="HQ yard"
        )
        with pytest.raises(ValidationError):
            return_stock(vehicle, branch=other_branch, location=location)


def test_full_journey_appends_one_movement_per_change(received, vehicle, branch, other_branch):
    """The three Phase 2 questions must be answerable from the movement log:
    where is it now, what state, and what is its complete history."""
    with company_scope(vehicle.company):
        adjust_stock_status(received, StockStatus.INSPECTION)   # ADJUSTMENT
        adjust_stock_status(received, StockStatus.AVAILABLE)    # ADJUSTMENT
        transfer_stock(received, other_branch)                  # TRANSFER
        move_stock(
            received,
            InventoryLocation.all_objects.create(
                company=vehicle.company, branch=other_branch, name="Showroom B"
            ),
        )                                                        # MOVE
        reserve_stock(vehicle)                                   # RESERVE
        sell_stock(vehicle)                                      # SALE
        deliver_stock(vehicle)                                   # DELIVERY
        return_stock(vehicle, branch=branch)                     # RETURN
    types = [m.movement_type for m in movements(vehicle).order_by("pk")]
    assert types == [
        MovementType.RECEIVE,
        MovementType.ADJUSTMENT,
        MovementType.ADJUSTMENT,
        MovementType.TRANSFER,
        MovementType.MOVE,
        MovementType.RESERVE,
        MovementType.SALE,
        MovementType.DELIVERY,
        MovementType.RETURN,
    ]
    stock = VehicleStock.all_objects.get(pk=received.pk)
    assert stock.status == StockStatus.AVAILABLE
    assert stock.branch == branch


def test_services_stamp_updated_at(received, vehicle, branch):
    before = received.updated_at
    with company_scope(vehicle.company):
        adjust_stock_status(received, StockStatus.INSPECTION)
    after = VehicleStock.all_objects.get(pk=received.pk).updated_at
    assert after > before
