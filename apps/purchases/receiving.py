"""Receiving a purchase order: appends immutable cost rows and creates
the authoritative stock row — all side effects are idempotent per line."""
from django.db import transaction

from apps.core.validation import validate_same_company
from apps.inventory.services import receive_vehicle

from .models import CostType, PurchaseOrder, PurchaseStatus, VehicleCostLine


@transaction.atomic
def receive_order(order: PurchaseOrder, user=None) -> int:
    """Mark an order received: for every line with a vehicle, append a
    purchase-price VehicleCostLine (if not already recorded) and initialize
    the vehicle's inventory stock with a RECEIVE movement (README §6.4).
    Returns vehicles received.

    Concurrency (README §26): the order row is locked with
    `select_for_update()` so two racing receivers serialize — the loser sees
    the committed RECEIVED status and stops. CANCELLED orders are never
    receivable (README §6.2: RECEIVED is reachable only through this
    service)."""
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    if order.status in (PurchaseStatus.RECEIVED, PurchaseStatus.CANCELLED):
        return 0
    # Cross-tenant references must be impossible through the write path
    # (README §25.2): the supplier and every received vehicle belong to
    # the order's company.
    validate_same_company(order.company, {"supplier": order.supplier})
    received = 0
    for line in order.lines.select_related("vehicle"):
        vehicle = line.vehicle
        if vehicle is None:
            continue
        validate_same_company(order.company, {"vehicle": vehicle})
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
        # Inventory state now lives exclusively on VehicleStock (§8): the
        # stock service creates the authoritative row and records RECEIVE.
        # `Vehicle.status` is deprecated legacy state and is no longer written.
        if branch:
            receive_vehicle(vehicle, branch, user=user, notes=f"PO {order}")
        received += 1
    order.status = PurchaseStatus.RECEIVED
    order.save(update_fields=["status", "updated_at"])
    return received
