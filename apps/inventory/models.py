"""Inventory architecture (README §8).

`VehicleStock` is the authoritative current inventory position — one row per
vehicle for its whole life. Physical history is preserved in append-only
`InventoryMovement` rows; every state/location change goes through the
services in `apps.inventory.services`, never direct saves.

Aging is always derived from the dated columns, never stored (§8.4).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import CompanyConsistencyMixin
from apps.core.tenancy import TenantModel


class LocationType(models.TextChoices):
    SHOWROOM = "showroom", _("Showroom")
    WAREHOUSE = "warehouse", _("Warehouse")
    YARD = "yard", _("Yard")
    WORKSHOP = "workshop", _("Workshop")
    INSPECTION = "inspection", _("Inspection")
    LOT = "lot", _("Lot")
    OTHER = "other", _("Other")


class InventoryLocation(TenantModel, CompanyConsistencyMixin):
    """Physical location inside a branch (§8.1)."""

    company_relations = ("branch",)

    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="locations",
        verbose_name=_("branch"),
    )
    name = models.CharField(_("name"), max_length=200)
    type = models.CharField(
        _("type"), max_length=20, choices=LocationType.choices, default=LocationType.OTHER
    )
    code = models.CharField(_("code"), max_length=50, blank=True)
    active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("inventory location")
        verbose_name_plural = _("inventory locations")
        ordering = ["branch__name", "name"]
        constraints = [
            # UNIQUE(company, branch, code) where code is populated (§8.1).
            models.UniqueConstraint(
                fields=["company", "branch", "code"],
                condition=~models.Q(code=""),
                name="unique_location_code_per_branch",
            ),
        ]

    def __str__(self):
        return f"{self.branch} / {self.name}"


class StockStatus(models.TextChoices):
    """Inventory lifecycle (§8.2). Not every vehicle passes every stage."""

    IN_TRANSIT = "in_transit", _("In transit")
    RECEIVED = "received", _("Received")
    INSPECTION = "inspection", _("Inspection")
    PREPARATION = "preparation", _("Preparation")
    AVAILABLE = "available", _("Available")
    RESERVED = "reserved", _("Reserved")
    SOLD = "sold", _("Sold")
    DELIVERED = "delivered", _("Delivered")


class VehicleCondition(models.TextChoices):
    """Physical condition — a dimension separate from availability (§8.2)."""

    NEW = "new", _("New")
    EXCELLENT = "excellent", _("Excellent")
    GOOD = "good", _("Good")
    FAIR = "fair", _("Fair")
    DAMAGED = "damaged", _("Damaged")
    NEEDS_REPAIR = "needs_repair", _("Needs repair")


class VehicleStock(TenantModel, CompanyConsistencyMixin):
    """One current stock row per vehicle (§8.2). Never deleted on sale or
    delivery: the row is historical evidence for aging and reporting."""

    company_relations = ("vehicle", "branch", "location")

    vehicle = models.OneToOneField(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="stock",
        verbose_name=_("vehicle"),
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="stock",
        verbose_name=_("branch"),
    )
    location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.SET_NULL,
        related_name="stock",
        verbose_name=_("location"),
        null=True,
        blank=True,
    )
    status = models.CharField(
        _("status"), max_length=20, choices=StockStatus.choices, default=StockStatus.RECEIVED
    )
    lot_code = models.CharField(_("lot / parking code"), max_length=50, blank=True)
    condition = models.CharField(
        _("condition"),
        max_length=20,
        choices=VehicleCondition.choices,
        default=VehicleCondition.NEW,
    )
    # received_at is not auto_now_add: the Phase 2 data migration backfills
    # rows with the vehicle's original creation date.
    received_at = models.DateTimeField(_("received at"), default=timezone.now)
    available_at = models.DateTimeField(_("available at"), null=True, blank=True)
    reserved_at = models.DateTimeField(_("reserved at"), null=True, blank=True)
    sold_at = models.DateTimeField(_("sold at"), null=True, blank=True)
    delivered_at = models.DateTimeField(_("delivered at"), null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    # Not auto_now: simple-history mirrors this model and cannot accept
    # auto-populated values; the inventory services stamp it explicitly.
    updated_at = models.DateTimeField(_("updated at"), default=timezone.now)

    class Meta:
        verbose_name = _("vehicle stock")
        verbose_name_plural = _("vehicle stock")
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.vehicle} @ {self.branch}"

    # ------------------------------------------------------------------
    # Inventory aging is derived, never stored (§8.4).
    # ------------------------------------------------------------------
    @property
    def days_in_inventory(self):
        if self.received_at is None:
            return None
        return (timezone.localdate() - self.received_at.date()).days

    @property
    def days_to_sale(self):
        if self.received_at is None or self.sold_at is None:
            return None
        return (self.sold_at.date() - self.received_at.date()).days

    @property
    def days_to_delivery(self):
        if self.received_at is None or self.delivered_at is None:
            return None
        return (self.delivered_at.date() - self.received_at.date()).days


class MovementType(models.TextChoices):
    """Append-only physical/state history (§8.3)."""

    RECEIVE = "receive", _("Receive")
    TRANSFER = "transfer", _("Transfer")
    MOVE = "move", _("Move")
    RESERVE = "reserve", _("Reserve")
    RELEASE = "release", _("Release")
    SALE = "sale", _("Sale")
    DELIVERY = "delivery", _("Delivery")
    RETURN = "return", _("Return")
    ADJUSTMENT = "adjustment", _("Adjustment")


class InventoryMovement(TenantModel, CompanyConsistencyMixin):
    """One row per state/location change; the complete movement history of a
    vehicle. Created exclusively by the inventory services (§8.3)."""

    company_relations = (
        "vehicle",
        "from_branch",
        "to_branch",
        "from_location",
        "to_location",
    )

    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="movements",
        verbose_name=_("vehicle"),
    )
    movement_type = models.CharField(
        _("movement type"), max_length=20, choices=MovementType.choices
    )
    from_branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("from branch"),
        null=True,
        blank=True,
    )
    to_branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("to branch"),
        null=True,
        blank=True,
    )
    from_location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("from location"),
        null=True,
        blank=True,
    )
    to_location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("to location"),
        null=True,
        blank=True,
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("performed by"),
        null=True,
        blank=True,
    )
    moved_at = models.DateTimeField(_("moved at"), default=timezone.now)
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("inventory movement")
        verbose_name_plural = _("inventory movements")
        ordering = ["-moved_at", "-id"]

    def __str__(self):
        return f"{self.get_movement_type_display()} — {self.vehicle}"
