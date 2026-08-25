"""Data migration 0005 (Phase 2 backfill, README §8): every vehicle gets one
authoritative `VehicleStock` row, lagging stock rows are promoted to the
legacy `Vehicle.status`, branch fallbacks apply, ADJUSTMENT movements record
every change, and the deprecated `Vehicle.status` is left untouched."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

import pytest

from apps.branches.models import Branch
from apps.inventory.models import InventoryMovement, VehicleStock

TARGET_0004 = [("inventory", "0004_historicalvehiclestock_available_at_and_more")]
TARGET_0005 = [("inventory", "0005_backfill_authoritative_stock")]


@pytest.mark.django_db(transaction=True)
def test_backfill_creates_promotes_and_preserves_legacy_status():
    executor = MigrationExecutor(connection)
    # Step back to the pre-backfill schema; 0005's reverse is a noop, so
    # the schema stays compatible with the current models.
    executor.migrate(TARGET_0004)
    old_apps = executor.loader.project_state(TARGET_0004).apps

    Organization = old_apps.get_model("organizations", "Organization")
    OldBranch = old_apps.get_model("branches", "Branch")
    OldVehicle = old_apps.get_model("vehicles", "Vehicle")
    OldStock = old_apps.get_model("inventory", "VehicleStock")

    company = Organization.objects.create(name="Legacy Co")
    lonely_company = Organization.objects.create(name="No Branches Co")
    hq = OldBranch.objects.create(company=company, name="HQ")

    # 1. Vehicle with a branch but no stock row (classic Phase 1 data).
    v_no_stock = OldVehicle.objects.create(
        company=company, vin="VIN00000000000001", make="Toyota", model="Corolla",
        year=2020, status="in_stock", branch=hq,
    )
    # 2. Vehicle with neither branch nor stock: falls back to the company's
    #    first branch.
    v_sold = OldVehicle.objects.create(
        company=company, vin="VIN00000000000002", make="Honda", model="Civic",
        year=2019, status="sold",
    )
    # 3. Stock row lagging behind the legacy vehicle status (reservations
    #    used to update only Vehicle.status).
    v_promo = OldVehicle.objects.create(
        company=company, vin="VIN00000000000003", make="Ford", model="Ranger",
        year=2021, status="reserved", branch=hq,
    )
    OldStock.objects.create(
        company=company, vehicle=v_promo, branch=hq,
        status="in_preparation", received_at=timezone.now(),
    )
    # 4. Stock row already ahead of the vehicle status: left alone.
    v_ahead = OldVehicle.objects.create(
        company=company, vin="VIN00000000000004", make="Kia", model="Sportage",
        year=2022, status="in_stock", branch=hq,
    )
    OldStock.objects.create(
        company=company, vehicle=v_ahead, branch=hq,
        status="available", received_at=timezone.now(),
    )
    # 5. A company with NO branches at all: the backfill creates "Main".
    v_main = OldVehicle.objects.create(
        company=lonely_company, vin="VIN00000000000005", make="Nissan",
        model="Sunny", year=2018, status="in_stock",
    )

    # A fresh executor is required: the applied-migration state is cached
    # per executor, and the recorder now says 0005 is unapplied.
    MigrationExecutor(connection).migrate(TARGET_0005)

    stocks = {
        stock.vehicle.vin: stock
        for stock in VehicleStock.all_objects.select_related("vehicle")
    }
    assert set(stocks) == {
        v_no_stock.vin, v_sold.vin, v_promo.vin, v_ahead.vin, v_main.vin,
    }

    # Missing rows were created with the correct mapped status + branch.
    assert stocks[v_no_stock.vin].status == "available"
    assert stocks[v_no_stock.vin].branch_id == hq.pk
    assert stocks[v_no_stock.vin].received_at == v_no_stock.created_at
    assert stocks[v_sold.vin].status == "sold"
    assert stocks[v_sold.vin].branch_id == hq.pk  # company's first branch

    # Lagging row was promoted (in_preparation -> preparation -> reserved).
    assert stocks[v_promo.vin].status == "reserved"
    # Already-ahead row was preserved.
    assert stocks[v_ahead.vin].status == "available"

    # The branch-less company got a "Main" branch (query by pk: the
    # company instance here is a historical model, not the live one).
    assert stocks[v_main.vin].branch_id == Branch.objects.get(
        company_id=lonely_company.pk, name="Main"
    ).pk

    # Every backfilled/promoted row is recorded in the movement history.
    backfilled = InventoryMovement.all_objects.filter(
        vehicle__vin__in=[v_no_stock.vin, v_sold.vin, v_promo.vin, v_main.vin],
        movement_type="adjustment",
    )
    assert backfilled.count() == 4
    assert all("Phase 2" in movement.notes for movement in backfilled)
    # The untouched row records nothing.
    assert not InventoryMovement.all_objects.filter(vehicle__vin=v_ahead.vin).exists()

    # The deprecated column survived untouched (§ deprecate later).
    from apps.vehicles.models import Vehicle

    legacy = {vehicle.vin: vehicle.status for vehicle in Vehicle.all_objects.all()}
    assert legacy[v_no_stock.vin] == "in_stock"
    assert legacy[v_sold.vin] == "sold"
    assert legacy[v_promo.vin] == "reserved"
    assert legacy[v_ahead.vin] == "in_stock"
    assert legacy[v_main.vin] == "in_stock"
