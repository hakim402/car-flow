"""The append-only financial ledger (agent.md §6, §10 Step 7).

Rules that are enforced at the model level, not by convention:
- Rows are never updated or deleted (`ImmutableModel` raises on both).
- Corrections are NEW rows referencing `reversal_of`.
- Current-state values (balances, outstanding amounts) are computed
  aggregates over these rows — see `apps.accounting.services`.
"""
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.models import ImmutableModel
from apps.core.tenancy import TenantModel


class EntryType(models.TextChoices):
    CUSTOMER_PAYMENT = "customer_payment", _("Customer payment")
    SUPPLIER_PAYMENT = "supplier_payment", _("Supplier payment")
    EXPENSE = "expense", _("Expense")
    OTHER = "other", _("Other")


# Money direction per entry type: in = received, out = paid.
ENTRY_DIRECTION = {
    EntryType.CUSTOMER_PAYMENT: "in",
    EntryType.SUPPLIER_PAYMENT: "out",
    EntryType.EXPENSE: "out",
    EntryType.OTHER: "in",
}


class LedgerEntry(TenantModel, ImmutableModel):
    """One immutable row per financial event. `related_object` points at the
    business document the money relates to (e.g. a Sale)."""

    type = models.CharField(_("type"), max_length=30, choices=EntryType.choices)
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, choices=CURRENCIES, default=DEFAULT_CURRENCY)
    description = models.CharField(_("description"), max_length=255, blank=True)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("related object type"),
        null=True,
        blank=True,
    )
    object_id = models.BigIntegerField(_("related object id"), null=True, blank=True)
    related_object = GenericForeignKey("content_type", "object_id")
    reversal_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="reversals",
        verbose_name=_("reversal of"),
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("ledger entry")
        verbose_name_plural = _("ledger entries")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} — {self.amount} {self.currency}"

    @property
    def direction(self) -> str:
        return ENTRY_DIRECTION.get(self.type, "in")

    @property
    def signed_amount(self):
        """Positive for money in, negative for money out."""
        return self.amount if self.direction == "in" else -self.amount
