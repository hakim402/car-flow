"""Sale-completion transactions (agent.md §10 Step 6).

State transitions touch several rows; each is a single atomic unit and
idempotent when repeated.
"""
import logging

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.communications import notification_engine
from apps.core.validation import validate_same_company
from apps.inventory.models import StockStatus, VehicleStock
from apps.inventory.services import sell_stock

from .models import Invoice, ReservationStatus, Sale, SaleStatus

logger = logging.getLogger(__name__)


@transaction.atomic
def complete_sale(sale: Sale, user=None) -> bool:
    """Mark a sale completed: flip the vehicle to SOLD and close the linked
    reservation. Returns False when the sale was already completed/cancelled."""
    validate_same_company(
        sale.company,
        {
            "customer": sale.customer,
            "vehicle": sale.vehicle,
            "reservation": sale.reservation,
        },
    )
    sale = Sale.objects.select_for_update().select_related("reservation").get(pk=sale.pk)
    if sale.status != SaleStatus.DRAFT:
        return False
    # Cross-tenant references must be impossible through the write path
    # (README §25.2).
    validate_same_company(
        sale.company,
        {
            "customer": sale.customer,
            "vehicle": sale.vehicle,
            "reservation": sale.reservation,
        },
    )
    stock = VehicleStock.objects.select_for_update().get(vehicle=sale.vehicle)
    if Sale.objects.filter(vehicle=sale.vehicle, status=SaleStatus.COMPLETED).exclude(
        pk=sale.pk
    ).exists():
        raise ValidationError(_("This vehicle already has a completed sale."))
    if sale.reservation:
        if sale.reservation.status != ReservationStatus.ACTIVE:
            raise ValidationError(_("The linked reservation is no longer active."))
        if sale.reservation.customer_id != sale.customer_id:
            raise ValidationError(_("Sale customer must match the reservation customer."))
        if sale.reservation.vehicle_id != sale.vehicle_id:
            raise ValidationError(_("Sale vehicle must match the reservation vehicle."))
        if stock.status != StockStatus.RESERVED:
            raise ValidationError(_("The reserved vehicle is not currently reserved in inventory."))
    elif stock.status != StockStatus.AVAILABLE:
        raise ValidationError(_("A direct sale requires an available vehicle."))
    # Inventory state lives on VehicleStock (§8): the stock service flips
    # AVAILABLE/RESERVED -> SOLD, stamps sold_at and appends a SALE
    # movement. `Vehicle.status` is deprecated legacy state.
    sell_stock(sale.vehicle, user=user, notes=f"Sale #{sale.pk}")
    if sale.reservation and sale.reservation.status == ReservationStatus.ACTIVE:
        sale.reservation.status = ReservationStatus.COMPLETED
        sale.reservation.save(update_fields=["status", "updated_at"])
    sale.status = SaleStatus.COMPLETED
    sale.save(update_fields=["status", "updated_at"])
    # §7.2: the single approved way business code reaches messaging.
    try:
        notification_engine.notify(
            "sale_completed",
            company=sale.company,
            customer=sale.customer,
            context={"vehicle": str(sale.vehicle)},
        )
    except Exception:  # notification must never break the sale
        logger.exception("sale_completed notification failed")
    return True


@transaction.atomic
def issue_invoice(sale: Sale, user=None) -> Invoice:
    """Issue the (single) invoice for a completed sale; idempotent.

    The `UNIQUE(sale)` database constraint (README §28) is the backstop for
    two concurrent requests: the loser catches `IntegrityError` and returns
    the winner's invoice instead of creating a duplicate."""
    existing = sale.invoices.first()
    if existing is not None:
        return existing
    try:
        # Inner atomic keeps the outer transaction usable after the
        # savepoint rollback triggered by a concurrent duplicate insert.
        with transaction.atomic():
            return Invoice.objects.create(
                company=sale.company,
                sale=sale,
                number=f"INV-{sale.pk:06d}",
                issued_on=timezone.localdate(),
                amount=sale.agreed_amount,
                currency=sale.currency,
                created_by=user if user and user.is_authenticated else None,
            )
    except IntegrityError:
        return sale.invoices.first()
