"""The append-only financial ledger (agent.md §6, §10 Step 7).

Rules that are enforced at the model level, not by convention:
- Rows are never updated or deleted (`ImmutableModel` raises on both).
- Corrections are NEW rows referencing `reversal_of`.
- Current-state values (balances, outstanding amounts) are computed
  aggregates over these rows — see `apps.accounting.services`.
"""
from datetime import date

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.models import CompanyConsistencyMixin, ImmutableModel
from apps.core.tenancy import TenantModel


class FinancialAccount(TenantModel):
    """A physical cash/bank account that funds flow through."""

    class AccountType(models.TextChoices):
        CASH = "CASH", _("Cash")
        BANK = "BANK", _("Bank")
        OTHER = "OTHER", _("Other")

    company_relations = ("branch",)

    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="financial_accounts",
        verbose_name=_("branch"),
        null=True,
        blank=True,
    )
    name = models.CharField(_("name"), max_length=200)
    account_type = models.CharField(
        _("account type"),
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.CASH,
    )
    currency = models.CharField(
        _("currency"),
        max_length=3,
        choices=CURRENCIES,
        default=DEFAULT_CURRENCY,
    )
    active = models.BooleanField(_("active"), default=True)
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("financial account")
        verbose_name_plural = _("financial accounts")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="unique_financial_account_name_per_company",
            )
        ]

    def __str__(self):
        return self.name


class PaymentMethod(models.TextChoices):
    CASH = "CASH", _("Cash")
    BANK_TRANSFER = "BANK_TRANSFER", _("Bank transfer")
    CARD = "CARD", _("Card")
    CHECK = "CHECK", _("Check")
    MOBILE_MONEY = "MOBILE_MONEY", _("Mobile money")
    OTHER = "OTHER", _("Other")


class EntryType(models.TextChoices):
    CUSTOMER_PAYMENT = "customer_payment", _("Customer payment")
    SUPPLIER_PAYMENT = "supplier_payment", _("Supplier payment")
    EXPENSE = "expense", _("Expense")
    REFUND = "refund", _("Refund")
    OTHER_IN = "other_in", _("Other inflow")
    OTHER_OUT = "other_out", _("Other outflow")
    OTHER = "other", _("Other")


# Money direction per entry type: in = received, out = paid.
ENTRY_DIRECTION = {
    EntryType.CUSTOMER_PAYMENT: "in",
    EntryType.SUPPLIER_PAYMENT: "out",
    EntryType.EXPENSE: "out",
    EntryType.REFUND: "out",
    EntryType.OTHER_IN: "in",
    EntryType.OTHER_OUT: "out",
    EntryType.OTHER: "in",
}


class LedgerSequence(TenantModel):
    """Concurrency-safe per-company counters for financial document numbers."""

    kind = models.CharField(_("sequence kind"), max_length=30)
    year = models.PositiveSmallIntegerField(_("year"))
    last_value = models.PositiveBigIntegerField(_("last value"), default=0)

    class Meta:
        verbose_name = _("ledger sequence")
        verbose_name_plural = _("ledger sequences")
        constraints = [
            models.UniqueConstraint(
                fields=["company", "kind", "year"],
                name="unique_ledger_sequence_per_company_year",
            )
        ]


class LedgerEntry(TenantModel, ImmutableModel, CompanyConsistencyMixin):
    """One immutable row per financial event. `related_object` points at the
    business document the money relates to (e.g. a Sale)."""

    company_relations = (
        "account",
        "customer",
        "sale",
        "reservation",
        "purchase_order",
        "supplier",
        "expense_category",
        "branch",
        "related_object",
    )

    type = models.CharField(_("type"), max_length=30, choices=EntryType.choices)
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, choices=CURRENCIES, default=DEFAULT_CURRENCY)
    account = models.ForeignKey(
        FinancialAccount,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("financial account"),
        null=True,
        blank=True,
    )
    payment_method = models.CharField(
        _("payment method"),
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.OTHER,
    )
    transaction_date = models.DateField(_("transaction date"), default=date.today)
    description = models.CharField(_("description"), max_length=255, blank=True)
    reference = models.CharField(_("reference"), max_length=100, blank=True)
    receipt_number = models.CharField(_("receipt number"), max_length=100, blank=True)
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("branch"),
        null=True,
        blank=True,
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("customer"),
        null=True,
        blank=True,
    )
    sale = models.ForeignKey(
        "sales.Sale",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("sale"),
        null=True,
        blank=True,
    )
    reservation = models.ForeignKey(
        "sales.Reservation",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("reservation"),
        null=True,
        blank=True,
    )
    purchase_order = models.ForeignKey(
        "purchases.PurchaseOrder",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("purchase order"),
        null=True,
        blank=True,
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("supplier"),
        null=True,
        blank=True,
    )
    expense_category = models.ForeignKey(
        "expenses.ExpenseCategory",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("expense category"),
        null=True,
        blank=True,
    )
    vendor = models.CharField(_("vendor / payee"), max_length=200, blank=True)
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
        constraints = [
            # One normal reversal per original entry, at the database level
            # (README §16, §28): racing corrections cannot double-reverse.
            models.UniqueConstraint(
                fields=["reversal_of"],
                condition=models.Q(reversal_of__isnull=False),
                name="one_reversal_per_ledger_entry",
            ),
            # Stored amounts are always positive (README §28); direction
            # comes from the entry type, never from a negative amount.
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="ledger_entry_amount_positive"),
            models.UniqueConstraint(
                fields=["company", "receipt_number"],
                condition=~models.Q(receipt_number=""),
                name="unique_receipt_number_per_company",
            ),
        ]

    def __str__(self):
        return f"{self.get_type_display()} — {self.amount} {self.currency}"

    @property
    def direction(self) -> str:
        return ENTRY_DIRECTION.get(self.type, "in")

    @property
    def signed_amount(self):
        """Positive for money in, negative for money out."""
        return self.amount if self.direction == "in" else -self.amount
