"""Phase 2 inventory data migration (README §8).

Before Phase 2, inventory state lived on `Vehicle.status` and stock rows were
only created at receiving time. This migration:

1. maps legacy stock statuses (`in_preparation` -> `preparation`);
2. promotes a stock row to the vehicle's legacy status when the vehicle is
   further along the lifecycle (sales/reservations used to update only
   `Vehicle.status`, so stock rows may lag behind);
3. creates the missing authoritative stock row for every vehicle, using the
   vehicle's branch, the company's first branch, or a new "Main" branch;
4. records an ADJUSTMENT movement for every backfilled row.

`Vehicle.status` itself is intentionally left untouched: Phase 2 keeps the
column as a deprecated legacy mirror and removes it in a later migration.
"""
from django.db import migrations
from django.utils import timezone

LEGACY_STOCK_MAP = {"in_preparation": "preparation"}

VEHICLE_STATUS_MAP = {
    "in_transit": "in_transit",
    "in_stock": "available",
    "reserved": "reserved",
    "sold": "sold",
    "delivered": "delivered",
}

STAGE = {
    "in_transit": 0,
    "received": 1,
    "inspection": 1,
    "preparation": 1,
    "available": 1,
    "reserved": 2,
    "sold": 3,
    "delivered": 4,
}


def backfill_stock(apps, schema_editor):
    Branch = apps.get_model("branches", "Branch")
    Vehicle = apps.get_model("vehicles", "Vehicle")
    VehicleStock = apps.get_model("inventory", "VehicleStock")
    InventoryMovement = apps.get_model("inventory", "InventoryMovement")

    # 1+2: reconcile existing stock rows with the legacy vehicle status.
    for stock in VehicleStock.objects.select_related("vehicle").all():
        new_status = LEGACY_STOCK_MAP.get(stock.status, stock.status)
        vehicle_status = VEHICLE_STATUS_MAP.get(stock.vehicle.status)
        if vehicle_status and STAGE[vehicle_status] > STAGE.get(new_status, 0):
            new_status = vehicle_status
        if new_status != stock.status:
            stock.status = new_status
            stock.save(update_fields=["status"])
            # A migration still mutates state: record it like any other
            # change so the movement history stays complete (§8.3).
            InventoryMovement.objects.create(
                company=stock.company,
                vehicle=stock.vehicle,
                movement_type="adjustment",
                notes=(
                    "Status reconciled from legacy Vehicle.status during "
                    "the Phase 2 inventory migration"
                ),
            )

    # 3+4: every vehicle gets exactly one authoritative stock row.
    now = timezone.now()
    for vehicle in Vehicle.objects.select_related("branch").all():
        if VehicleStock.objects.filter(vehicle=vehicle).exists():
            continue
        branch = vehicle.branch
        if branch is None:
            branch = Branch.objects.filter(company=vehicle.company).first()
        if branch is None:
            branch = Branch.objects.create(company=vehicle.company, name="Main")
        VehicleStock.objects.create(
            company=vehicle.company,
            vehicle=vehicle,
            branch=branch,
            status=VEHICLE_STATUS_MAP.get(vehicle.status, "received"),
            received_at=vehicle.created_at or now,
            created_at=now,
            updated_at=now,
        )
        InventoryMovement.objects.create(
            company=vehicle.company,
            vehicle=vehicle,
            movement_type="adjustment",
            to_branch=branch,
            moved_at=now,
            notes=(
                "Backfilled from legacy Vehicle.status during the Phase 2 "
                "inventory migration"
            ),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("branches", "0001_initial"),
        ("inventory", "0004_historicalvehiclestock_available_at_and_more"),
        ("organizations", "0001_initial"),
        ("vehicles", "0002_historicalvehicle"),
    ]

    operations = [
        migrations.RunPython(backfill_stock, migrations.RunPython.noop),
    ]
