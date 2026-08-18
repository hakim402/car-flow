"""Receiving a purchase order: appends immutable cost rows and creates
branch stock — all side effects are idempotent per line."""
from django.db import transaction

from apps.inventory.models import VehicleStock
from apps.vehicles.models import VehicleStatus

from .models import CostType, PurchaseOrder, PurchaseStatus, VehicleCostLine


@transaction.atomic
def receive_order(order: PurchaseOrder, user=None) -> int:
    """Mark an order received: for every line with a vehicle, append a
    purchase-price VehicleCostLine (if not already recorded), place the
    vehicle into branch stock, and flip its status. Returns vehicles received."""
    if order.status == PurchaseStatus.RECEIVED:
        return 0
    received = 0
    for line in order.lines.select_related("vehicle"):
        vehicle = line.vehicle
        if vehicle is None:
            continue
        already = VehicleCostLine.objects.filter(
            vehicle=vehicle,
            cost_type=CostType.PURCHASE,
            amount=line.amount,
            currency=line.currency,
            description=f"PO {order}",
        ).exists()
        if not already:
            VehicleCostLine.objects.create(
                company=order.company,
                vehicle=vehicle,
                cost_type=CostType.PURCHASE,
                amount=line.amount,
                currency=line.currency,
                description=f"PO {order}",
                created_by=user if user and user.is_authenticated else None,
            )
        branch = order.branch or vehicle.branch
        if branch:
            vehicle.branch = branch
        vehicle.status = VehicleStatus.IN_STOCK
        vehicle.save()
        if branch:
            VehicleStock.objects.get_or_create(
                vehicle=vehicle,
                defaults={"company": order.company, "branch": branch},
            )
        received += 1
    order.status = PurchaseStatus.RECEIVED
    order.save(update_fields=["status", "updated_at"])
    return received
