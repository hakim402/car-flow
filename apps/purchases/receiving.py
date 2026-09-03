"""Receiving a purchase order: appends immutable cost rows and creates
the authoritative stock row — all side effects are idempotent per line."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

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
    required_status = PurchaseStatus.CUSTOMS if order.is_import else PurchaseStatus.ORDERED
    if order.status != required_status:
        raise ValidationError(
            _("This purchase order must be %(status)s before it can be received."),
            params={"status": PurchaseStatus(required_status).label},
        )

    lines = list(order.lines.select_related("vehicle"))
    vehicle_lines = [line for line in lines if line.vehicle_id]
    if not vehicle_lines:
        raise ValidationError(_("Add at least one vehicle line before receiving this order."))

    # Validate the complete batch before writing the first cost or stock row.
    # The transaction would roll back on failure either way, but preflight
    # validation makes the all-or-nothing receiving contract explicit.
    for line in vehicle_lines:
        validate_same_company(order.company, {"vehicle": line.vehicle})
        if order.branch is None and line.vehicle.branch is None:
            raise ValidationError(
                _("Choose a receiving branch for every vehicle before receiving this order.")
            )

    received = 0
    for line in vehicle_lines:
        vehicle = line.vehicle
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
        receive_vehicle(vehicle, branch, user=user, notes=f"PO {order}")
        received += 1
    order.status = PurchaseStatus.RECEIVED
    order.save(update_fields=["status", "updated_at"])
    return received
