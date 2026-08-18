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

from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.models import ImmutableModel
from apps.core.tenancy import TenantModel


class PurchaseStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ORDERED = "ordered", _("Ordered")
    RECEIVED = "received", _("Received")
    CANCELLED = "cancelled", _("Cancelled")


class PurchaseOrder(TenantModel):
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
    order_date = models.DateField(_("order date"))
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

    def __str__(self):
        return f"{self.description} — {self.amount} {self.currency}"


class CostType(models.TextChoices):
    PURCHASE = "purchase", _("Purchase price")
    TRANSPORT = "transport", _("Transport")
    CUSTOMS = "customs", _("Customs & duties")
    STORAGE = "storage", _("Storage")
    REPAIR = "repair", _("Repair & preparation")
    OTHER = "other", _("Other")


class VehicleCostLine(TenantModel, ImmutableModel):
    """One immutable row per cost event on a vehicle (§6)."""

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

    def __str__(self):
        return f"{self.get_cost_type_display()} — {self.amount} {self.currency}"
