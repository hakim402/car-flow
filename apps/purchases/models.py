"""Purchasing models (agent.md §10 Step 5, §6, §9).

- Order totals are computed from lines — never stored.
- `VehicleCostLine` is the immutable cost-event ledger for a vehicle:
  one row per event (purchase, transport, customs, storage, repair).
  Landed cost is an aggregate over those rows, never a stored column.
"""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.constants import COUNTRIES, CURRENCIES, DEFAULT_CURRENCY
from apps.core.models import CompanyConsistencyMixin, ImmutableModel
from apps.core.tenancy import TenantModel


class PurchaseType(models.TextChoices):
    DOMESTIC = "domestic", _("Domestic purchase")
    IMPORT = "import", _("Import from abroad")


class PurchaseStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ORDERED = "ordered", _("Ordered")
    SHIPPED = "shipped", _("In transit")
    CUSTOMS = "customs", _("At customs")
    RECEIVED = "received", _("Received")
    CANCELLED = "cancelled", _("Cancelled")


class Incoterms(models.TextChoices):
    EXW = "EXW", "EXW"
    FOB = "FOB", "FOB"
    CFR = "CFR", "CFR"
    CIF = "CIF", "CIF"
    DAP = "DAP", "DAP"
    DDP = "DDP", "DDP"


class ShippingMethod(models.TextChoices):
    CONTAINER = "container", _("Container (sea)")
    RO_RO = "ro_ro", _("Ro-Ro vessel")
    LAND = "land", _("Land transport")
    AIR = "air", _("Air freight")
    OTHER = "other", _("Other")


#: Legal forward steps of the status workflow — receiving (with its stock
#: side effects) is reached only through `receive_order`, never this map.
NEXT_STATUS = {
    PurchaseStatus.DRAFT: PurchaseStatus.ORDERED,
    PurchaseStatus.ORDERED: PurchaseStatus.SHIPPED,
    PurchaseStatus.SHIPPED: PurchaseStatus.CUSTOMS,
}


class PurchaseOrder(TenantModel, CompanyConsistencyMixin):
    company_relations = ("supplier", "branch")

    reference = models.CharField(_("reference"), max_length=50, blank=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name=_("supplier"),
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name=_("branch"),
        null=True,
        blank=True,
    )
    status = models.CharField(
        _("status"), max_length=20, choices=PurchaseStatus.choices, default=PurchaseStatus.DRAFT
    )
    purchase_type = models.CharField(
        _("purchase type"),
        max_length=20,
        choices=PurchaseType.choices,
        default=PurchaseType.DOMESTIC,
    )
    order_date = models.DateField(_("order date"))
    # Import/shipment tracking — filled when vehicles arrive from abroad.
    origin_country = models.CharField(
        _("origin country"), max_length=5, choices=COUNTRIES, blank=True
    )
    incoterms = models.CharField(
        _("incoterms"), max_length=10, choices=Incoterms.choices, blank=True
    )
    shipping_method = models.CharField(
        _("shipping method"), max_length=20, choices=ShippingMethod.choices, blank=True
    )
    bill_of_lading_no = models.CharField(_("bill of lading no."), max_length=100, blank=True)
    container_no = models.CharField(_("container no."), max_length=100, blank=True)
    shipped_date = models.DateField(_("shipped date"), null=True, blank=True)
    eta = models.DateField(_("expected arrival"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("purchase order")
        verbose_name_plural = _("purchase orders")
        ordering = ["-created_at"]

    def __str__(self):
        return self.reference or f"PO #{self.pk}"

    def get_absolute_url(self):
        return reverse("purchases:detail", kwargs={"pk": self.pk})

    def total_by_currency(self) -> dict[str, object]:
        """Computed total per currency (§6: aggregates over rows, not stored)."""
        totals: dict[str, object] = {}
        for line in self.lines.all():
            totals[line.currency] = totals.get(line.currency, 0) + line.amount
        return totals

    @property
    def is_import(self):
        return self.purchase_type == PurchaseType.IMPORT

    @property
    def next_status(self):
        """Status this order advances to next, or None at a dead end.
        Imports walk draft → ordered → shipped → customs; domestic orders
        only confirm, then go straight to receiving."""
        if self.is_import:
            return NEXT_STATUS.get(self.status)
        if self.status == PurchaseStatus.DRAFT:
            return PurchaseStatus.ORDERED
        return None


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="lines", verbose_name=_("order")
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="purchase_lines",
        verbose_name=_("vehicle"),
        null=True,
        blank=True,
    )
    description = models.CharField(_("description"), max_length=255)
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, choices=CURRENCIES, default=DEFAULT_CURRENCY)

    class Meta:
        verbose_name = _("purchase order line")
        verbose_name_plural = _("purchase order lines")
        constraints = [
            # Money rows are positive (README §28).
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="po_line_amount_positive"),
        ]

    def __str__(self):
        return f"{self.description} — {self.amount} {self.currency}"


class CostType(models.TextChoices):
    PURCHASE = "purchase", _("Purchase price")
    TRANSPORT = "transport", _("Transport")
    CUSTOMS = "customs", _("Customs & duties")
    STORAGE = "storage", _("Storage")
    REPAIR = "repair", _("Repair & preparation")
    OTHER = "other", _("Other")


class VehicleCostLine(TenantModel, ImmutableModel, CompanyConsistencyMixin):
    """One immutable row per cost event on a vehicle (§6)."""

    company_relations = ("vehicle",)

    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="cost_lines",
        verbose_name=_("vehicle"),
    )
    cost_type = models.CharField(_("cost type"), max_length=20, choices=CostType.choices)
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, choices=CURRENCIES, default=DEFAULT_CURRENCY)
    description = models.CharField(_("description"), max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vehicle_cost_lines",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("vehicle cost line")
        verbose_name_plural = _("vehicle cost lines")
        ordering = ["created_at"]
        constraints = [
            # Stored amounts are always positive (README §28).
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="vehicle_cost_line_amount_positive"),
        ]

    def __str__(self):
        return f"{self.get_cost_type_display()} — {self.amount} {self.currency}"
