"""PostgreSQL concurrency gates for the inventory mutation layer (README §26).

Every state change on a `VehicleStock` row goes through `select_for_update()`,
so racing writers serialize: whoever locks first wins, the loser observes the
committed state and must not double-append movements. SQLite has a
single-writer model, so these tests only run against PostgreSQL:

    docker compose run --rm web pytest --ds=config.settings.test_postgres \\
        apps/inventory/tests/test_inventory_concurrency.py
"""
import threading

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.branches.models import Branch
from apps.core.tenancy import company_scope
from apps.core.testing import OrganizationFactory, VehicleFactory
from apps.inventory.models import InventoryMovement, MovementType, StockStatus, VehicleStock
from apps.inventory.services import (
    adjust_stock_status,
    deliver_stock,
    receive_vehicle,
    reserve_stock,
    sell_stock,
    transfer_stock as transfer,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL concurrency semantics required (README §26)",
    ),
]


def _run_concurrently(fns):
    """Run each callable in its own thread with a fresh DB connection, all
    released from the same barrier. Returns (results, errors)."""
    barrier = threading.Barrier(len(fns))
    results = [None] * len(fns)
    errors = [None] * len(fns)

    def worker(index):
        try:
            connection.close()  # fresh connection per thread
            results[index] = fns[index](barrier)
        except Exception as exc:  # noqa: BLE001 - collected for the asserts
            errors[index] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(fns))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, errors


@pytest.fixture
def available_stock():
    company = OrganizationFactory()
    branch = Branch.objects.create(company=company, name="HQ")
    vehicle = VehicleFactory(company=company)
    with company_scope(company):
        stock = receive_vehicle(vehicle, branch)
        adjust_stock_status(stock, StockStatus.AVAILABLE)
    return stock


def _movement_count(vehicle, movement_type):
    return InventoryMovement.all_objects.filter(
        vehicle=vehicle, movement_type=movement_type
    ).count()


def test_two_racing_reservations_append_one_reserve_movement(available_stock):
    stock = available_stock

    def call(barrier):
        with company_scope(stock.company), transaction.atomic():
            barrier.wait()
            return reserve_stock(stock.vehicle).pk

    results, errors = _run_concurrently([call, call])
    assert errors == [None, None]
    assert results[0] == results[1]  # both ended on the same row
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    assert stock.status == StockStatus.RESERVED
    assert stock.reserved_at is not None
    # The row lock is what makes this one movement instead of two.
    assert _movement_count(stock.vehicle, MovementType.RESERVE) == 1


def test_two_racing_sales_append_one_sale_movement(available_stock):
    stock = available_stock

    def call(barrier):
        with company_scope(stock.company), transaction.atomic():
            barrier.wait()
            return sell_stock(stock.vehicle).pk

    results, errors = _run_concurrently([call, call])
    assert errors == [None, None]
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    assert stock.status == StockStatus.SOLD
    assert _movement_count(stock.vehicle, MovementType.SALE) == 1


def test_racing_reserve_and_sale_serialize_into_sold(available_stock):
    """Reserve and sell racing on an AVAILABLE row: the sale must always
    win in the end and exactly one SALE movement may exist."""
    stock = available_stock

    def reserve(barrier):
        with company_scope(stock.company), transaction.atomic():
            barrier.wait()
            return reserve_stock(stock.vehicle).pk

    def sell(barrier):
        with company_scope(stock.company), transaction.atomic():
            barrier.wait()
            return sell_stock(stock.vehicle).pk

    results, errors = _run_concurrently([reserve, sell])
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    # Sale either ran first (reserve then fails) or ran after the reserve —
    # either way the final state is SOLD with a single SALE movement.
    assert stock.status == StockStatus.SOLD
    assert _movement_count(stock.vehicle, MovementType.SALE) == 1
    assert _movement_count(stock.vehicle, MovementType.RESERVE) <= 1
    failed = [e for e in errors if e is not None]
    for exc in failed:
        assert isinstance(exc, ValidationError)


def test_racing_transfers_land_on_a_consistent_branch(available_stock):
    """Two competing transfers: both may succeed serially, but the final
    state and the movement log must agree."""
    stock = available_stock

    branch_a = Branch.objects.create(company=stock.company, name="A")
    branch_b = Branch.objects.create(company=stock.company, name="B")

    def transfer_a(barrier):
        with company_scope(stock.company), transaction.atomic():
            barrier.wait()
            return transfer(stock, branch_a).branch_id

    def transfer_b(barrier):
        with company_scope(stock.company), transaction.atomic():
            barrier.wait()
            return transfer(stock, branch_b).branch_id

    results, errors = _run_concurrently([transfer_a, transfer_b])
    assert errors == [None, None]
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    movements = InventoryMovement.all_objects.filter(
        vehicle=stock.vehicle, movement_type=MovementType.TRANSFER
    ).order_by("pk")
    # The last movement always matches the current position.
    assert movements.last().to_branch_id == stock.branch_id
    assert stock.branch_id in {branch_a.pk, branch_b.pk}
    assert len(movements) >= 1


def test_sale_and_delivery_race_never_skips_delivery(available_stock):
    """A delivery racing a sale: delivery may fail fast (still available) or
    land after the sale — the final state must be DELIVERED or SOLD, and the
    movement log must never contain a delivery without its sale."""
    stock = available_stock

    def sell(barrier):
        with company_scope(stock.company), transaction.atomic():
            barrier.wait()
            return sell_stock(stock.vehicle).pk

    def deliver(barrier):
        with company_scope(stock.company), transaction.atomic():
            barrier.wait()
            return deliver_stock(stock.vehicle).pk

    results, errors = _run_concurrently([sell, deliver])
    stock = VehicleStock.all_objects.get(pk=stock.pk)
    sales = _movement_count(stock.vehicle, MovementType.SALE)
    deliveries = _movement_count(stock.vehicle, MovementType.DELIVERY)
    if stock.status == StockStatus.DELIVERED:
        # Sale won the lock first; delivery landed right behind it.
        assert sales == 1 and deliveries == 1
        assert all(e is None for e in errors)
    else:
        # Delivery lost the race and failed cleanly on the still-AVAILABLE
        # row; the sale then completed alone.
        assert stock.status == StockStatus.SOLD
        assert sales == 1 and deliveries == 0
        failures = [e for e in errors if e is not None]
        assert len(failures) == 1
        assert isinstance(failures[0], ValidationError)
