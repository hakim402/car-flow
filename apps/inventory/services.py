"""Inventory mutation service layer (README §8.3).

Every state/location change runs through these services, inside one
transaction: they update `VehicleStock` and append the corresponding
`InventoryMovement` together. Concurrency-sensitive paths lock the stock row
with `select_for_update()` before checking status, so two racing writers
serialize (§26). Direct saves of `VehicleStock` outside this module are
never the way to change inventory state.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.validation import validate_same_company

from .models import (
    InventoryMovement,
    MovementType,
    StockStatus,
    VehicleCondition,
    VehicleStock,
)

# The lifecycle permits only these transitions (§8.2). Not every vehicle
# passes every stage, but skipping is only possible where listed.
ALLOWED_TRANSITIONS = {
    StockStatus.IN_TRANSIT: {StockStatus.RECEIVED},
    StockStatus.RECEIVED: {
        StockStatus.INSPECTION,
        StockStatus.PREPARATION,
        StockStatus.AVAILABLE,
    },
    StockStatus.INSPECTION: {StockStatus.PREPARATION, StockStatus.AVAILABLE},
    StockStatus.PREPARATION: {StockStatus.AVAILABLE},
    StockStatus.AVAILABLE: {StockStatus.RESERVED, StockStatus.SOLD},
    StockStatus.RESERVED: {StockStatus.AVAILABLE, StockStatus.SOLD},
    StockStatus.SOLD: {StockStatus.DELIVERED, StockStatus.AVAILABLE},
    StockStatus.DELIVERED: {StockStatus.AVAILABLE},
}

# Dated column stamped when a status is entered; aging derives from these.
STATUS_TIMESTAMP = {
    StockStatus.AVAILABLE: "available_at",
    StockStatus.RESERVED: "reserved_at",
    StockStatus.SOLD: "sold_at",
    StockStatus.DELIVERED: "delivered_at",
}


def _user_id(user):
    return user.pk if user is not None and user.is_authenticated else None


def _locked(stock):
    """Re-read and lock the stock row: the only safe way to mutate state
    under concurrency (README §26)."""
    return VehicleStock.objects.select_for_update().get(pk=stock.pk)


def _locked_by_vehicle(vehicle):
    try:
        return VehicleStock.objects.select_for_update().get(vehicle=vehicle)
    except VehicleStock.DoesNotExist:
        raise ValidationError(
            _("Vehicle %(vehicle)s has no inventory stock row.")
            % {"vehicle": vehicle}
        )


def _movement(
    stock,
    movement_type,
    *,
    user=None,
    notes="",
    from_branch=None,
    to_branch=None,
    from_location=None,
    to_location=None,
):
    return InventoryMovement.objects.create(
        company=stock.company,
        vehicle=stock.vehicle,
        movement_type=movement_type,
        from_branch=from_branch,
        to_branch=to_branch,
        from_location=from_location,
        to_location=to_location,
        performed_by_id=_user_id(user),
        notes=notes,
    )


def _set_status(stock, new_status, *, user=None, notes="", movement_type):
    """Guarded status change + the movement that proves it happened."""
    stock = _locked(stock)
    if new_status == stock.status:
        return stock
    if new_status not in ALLOWED_TRANSITIONS.get(stock.status, set()):
        raise ValidationError(
            _("Invalid inventory transition: %(from)s → %(to)s.")
            % {
                "from": stock.get_status_display(),
                "to": dict(StockStatus.choices)[new_status],
            }
        )
    now = timezone.now()
    stock.status = new_status
    update_fields = ["status", "updated_at"]
    timestamp_field = STATUS_TIMESTAMP.get(new_status)
    if timestamp_field is not None:
        setattr(stock, timestamp_field, now)
        update_fields.append(timestamp_field)
    stock.updated_at = now
    stock.save(update_fields=update_fields)
    _movement(stock, movement_type, user=user, notes=notes)
    return stock


@transaction.atomic
def receive_vehicle(
    vehicle,
    branch,
    *,
    user=None,
    location=None,
    notes="",
    condition=VehicleCondition.NEW,
):
    """Create the authoritative stock row when a vehicle physically arrives
    (§6.4) and record RECEIVE. Idempotent: if the row already exists it is
    returned unchanged and no extra movement is written."""
    validate_same_company(vehicle.company, {"branch": branch, "location": location})
    stock, created = VehicleStock.objects.get_or_create(
        vehicle=vehicle,
        defaults={
            "company": vehicle.company,
            "branch": branch,
            "location": location,
            "status": StockStatus.RECEIVED,
            "condition": condition,
            "received_at": timezone.now(),
        },
    )
    if created:
        _movement(
            stock,
            MovementType.RECEIVE,
            user=user,
            notes=notes or _("Vehicle received"),
            to_branch=branch,
            to_location=location,
        )
    return stock


@transaction.atomic
def transfer_stock(stock, to_branch, *, user=None, to_location=None, notes=""):
    """Move a vehicle to another branch (TRANSFER movement)."""
    stock = _locked(stock)
    validate_same_company(
        stock.company, {"to branch": to_branch, "to location": to_location}
    )
    if stock.status == StockStatus.DELIVERED:
        raise ValidationError(_("A delivered vehicle cannot be transferred — use a return."))
    if to_location is not None and to_location.branch_id != to_branch.pk:
        raise ValidationError(_("The location does not belong to the target branch."))
    if stock.branch_id == to_branch.pk and (stock.location_id or None) == (
        to_location.pk if to_location else None
    ):
        return stock  # nothing to do — no movement for a no-op
    from_branch, from_location = stock.branch, stock.location
    stock.branch = to_branch
    stock.location = to_location
    stock.updated_at = timezone.now()
    stock.save(update_fields=["branch", "location", "updated_at"])
    _movement(
        stock,
        MovementType.TRANSFER,
        user=user,
        notes=notes,
        from_branch=from_branch,
        to_branch=to_branch,
        from_location=from_location,
        to_location=to_location,
    )
    return stock


@transaction.atomic
def move_stock(stock, to_location, *, user=None, notes=""):
    """Internal move between locations of the same branch (MOVE movement)."""
    stock = _locked(stock)
    validate_same_company(stock.company, {"to location": to_location})
    if to_location.branch_id != stock.branch_id:
        raise ValidationError(
            _("The location must belong to the same branch — use a transfer.")
        )
    if (stock.location_id or None) == to_location.pk:
        return stock  # no-op
    from_location = stock.location
    stock.location = to_location
    stock.updated_at = timezone.now()
    stock.save(update_fields=["location", "updated_at"])
    _movement(
        stock,
        MovementType.MOVE,
        user=user,
        notes=notes,
        from_location=from_location,
        to_location=to_location,
    )
    return stock


@transaction.atomic
def reserve_stock(vehicle, *, user=None, notes=""):
    """AVAILABLE → RESERVED (RESERVE movement). Called by the reservation
    write path; the row lock makes double-reservation impossible (§11)."""
    stock = _locked_by_vehicle(vehicle)
    return _set_status(stock, StockStatus.RESERVED, user=user, notes=notes,
                       movement_type=MovementType.RESERVE)


@transaction.atomic
def release_stock(vehicle, *, user=None, notes=""):
    """RESERVED → AVAILABLE when a reservation is cancelled/expired
    (RELEASE movement). Tolerates an already-available vehicle."""
    stock = _locked_by_vehicle(vehicle)
    if stock.status == StockStatus.AVAILABLE:
        return stock
    return _set_status(stock, StockStatus.AVAILABLE, user=user, notes=notes,
                       movement_type=MovementType.RELEASE)


@transaction.atomic
def sell_stock(vehicle, *, user=None, notes=""):
    """AVAILABLE/RESERVED → SOLD (SALE movement). Idempotent for an
    already-sold vehicle so repeated sale completions stay safe."""
    stock = _locked_by_vehicle(vehicle)
    if stock.status == StockStatus.SOLD:
        return stock
    return _set_status(stock, StockStatus.SOLD, user=user, notes=notes,
                       movement_type=MovementType.SALE)


@transaction.atomic
def deliver_stock(vehicle, *, user=None, notes=""):
    """SOLD → DELIVERED (DELIVERY movement, §21). Idempotent."""
    stock = _locked_by_vehicle(vehicle)
    if stock.status == StockStatus.DELIVERED:
        return stock
    return _set_status(stock, StockStatus.DELIVERED, user=user, notes=notes,
                       movement_type=MovementType.DELIVERY)


@transaction.atomic
def return_stock(vehicle, *, user=None, notes="", branch=None, location=None):
    """Bring a sold/delivered vehicle back into available stock (RETURN
    movement), optionally placing it at a specific branch/location."""
    stock = _locked_by_vehicle(vehicle)
    validate_same_company(stock.company, {"branch": branch, "location": location})
    if location is not None:
        if branch is None:
            branch = location.branch
        elif location.branch_id != branch.pk:
            raise ValidationError(_("The location does not belong to the target branch."))
    changed = []
    if branch is not None and stock.branch_id != branch.pk:
        stock.branch = branch
        changed.append("branch")
    if location is not None and (stock.location_id or None) != location.pk:
        stock.location = location
        changed.append("location")
    if changed:
        stock.updated_at = timezone.now()
        stock.save(update_fields=[*changed, "updated_at"])
    return _set_status(
        stock,
        StockStatus.AVAILABLE,
        user=user,
        notes=notes or _("Vehicle returned to inventory"),
        movement_type=MovementType.RETURN,
    )


@transaction.atomic
def adjust_stock_status(stock, new_status, *, user=None, notes=""):
    """Guarded manual lifecycle change (e.g. INSPECTION / PREPARATION /
    AVAILABLE), recorded as an ADJUSTMENT movement. Named business services
    remain the preferred path for reserve/sale/delivery transitions."""
    if new_status == stock.status:
        return _locked(stock)
    return _set_status(stock, new_status, user=user, notes=notes,
                       movement_type=MovementType.ADJUSTMENT)
