"""Financing agreements and immutable installment/payment allocation history."""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.models import CompanyConsistencyMixin, ImmutableModel
from apps.core.tenancy import TenantModel


class FinancingPartner(TenantModel):
    class PartnerType(models.TextChoices):
        BANK = "bank", _("Bank")
        MICROFINANCE = "microfinance", _("Microfinance institution")
        OTHER = "other", _("Other")

    name = models.CharField(_("name"), max_length=200)
    partner_type = models.CharField(
        _("partner type"), max_length=20, choices=PartnerType.choices, default=PartnerType.BANK
    )
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    email = models.EmailField(_("email"), blank=True)
    active = models.BooleanField(_("active"), default=True)
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="unique_financing_partner_name_per_company"
            )
        ]

    def __str__(self):
        return self.name


class AgreementType(models.TextChoices):
    DEALER_INSTALLMENT = "dealer_installment", _("Dealer installment")
    EXTERNAL_LENDER = "external_lender", _("External lender")


class AgreementStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PENDING_APPROVAL = "pending_approval", _("Pending approval")
    ACTIVE = "active", _("Active")
    COMPLETED = "completed", _("Completed")
    DEFAULTED = "defaulted", _("Defaulted")
    CANCELLED = "cancelled", _("Cancelled")


class PaymentFrequency(models.TextChoices):
    WEEKLY = "weekly", _("Weekly")
    BIWEEKLY = "biweekly", _("Every two weeks")
    MONTHLY = "monthly", _("Monthly")


class FinanceAgreement(TenantModel, CompanyConsistencyMixin):
    """Commercial terms are editable only before activation."""

    company_relations = (
        "sale",
        "branch",
        "partner",
        "created_by",
        "approved_by",
    )
    protected_term_fields = (
        "sale_id",
        "agreement_type",
        "partner_id",
        "currency",
        "cash_price",
        "markup_amount",
        "down_payment_required",
        "installment_count",
        "frequency",
        "first_due_date",
        "grace_days",
    )

    number = models.CharField(_("agreement number"), max_length=50)
    sale = models.OneToOneField(
        "sales.Sale", on_delete=models.PROTECT, related_name="finance_agreement", verbose_name=_("sale")
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="finance_agreements",
        verbose_name=_("branch"),
        null=True,
        blank=True,
    )
    agreement_type = models.CharField(
        _("financing type"),
        max_length=30,
        choices=AgreementType.choices,
        default=AgreementType.DEALER_INSTALLMENT,
    )
    partner = models.ForeignKey(
        FinancingPartner,
        on_delete=models.PROTECT,
        related_name="agreements",
        verbose_name=_("financing partner"),
        null=True,
        blank=True,
    )
    external_reference = models.CharField(_("external reference"), max_length=100, blank=True)
    currency = models.CharField(
        _("currency"), max_length=3, choices=CURRENCIES, default=DEFAULT_CURRENCY
    )
    cash_price = models.DecimalField(_("cash price"), max_digits=14, decimal_places=2)
    markup_amount = models.DecimalField(
        _("fixed markup / profit"), max_digits=14, decimal_places=2, default=Decimal("0")
    )
    down_payment_required = models.DecimalField(
        _("required down payment"), max_digits=14, decimal_places=2, default=Decimal("0")
    )
    installment_count = models.PositiveSmallIntegerField(_("number of installments"))
    frequency = models.CharField(
        _("payment frequency"),
        max_length=20,
        choices=PaymentFrequency.choices,
        default=PaymentFrequency.MONTHLY,
    )
    first_due_date = models.DateField(_("first due date"))
    grace_days = models.PositiveSmallIntegerField(_("grace days"), default=0)
    status = models.CharField(
        _("status"), max_length=30, choices=AgreementStatus.choices, default=AgreementStatus.DRAFT
    )
    customer_snapshot = models.JSONField(_("customer snapshot"), default=dict, blank=True)
    vehicle_snapshot = models.JSONField(_("vehicle snapshot"), default=dict, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_finance_agreements",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_finance_agreements",
        verbose_name=_("approved by"),
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    activated_at = models.DateTimeField(_("activated at"), null=True, blank=True)
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "number"], name="unique_finance_agreement_number_per_company"
            ),
            models.CheckConstraint(condition=models.Q(cash_price__gt=0), name="finance_cash_price_positive"),
            models.CheckConstraint(condition=models.Q(markup_amount__gte=0), name="finance_markup_nonnegative"),
            models.CheckConstraint(
                condition=models.Q(down_payment_required__gte=0), name="finance_down_payment_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(installment_count__gt=0), name="finance_installment_count_positive"
            ),
        ]

    @property
    def total_sale_price(self):
        return (self.cash_price or Decimal("0")) + (self.markup_amount or Decimal("0"))

    @property
    def amount_financed(self):
        return self.total_sale_price - (self.down_payment_required or Decimal("0"))

    def clean(self):
        super().clean()
        errors = {}
        if self.sale_id:
            if self.currency != self.sale.currency:
                errors["currency"] = _("Agreement currency must match the sale currency.")
            if self.total_sale_price != self.sale.agreed_amount:
                errors["cash_price"] = _(
                    "Cash price plus markup must equal the sale's agreed amount."
                )
        if self.down_payment_required is not None and self.down_payment_required > self.total_sale_price:
            errors["down_payment_required"] = _("Down payment cannot exceed the total sale price.")
        if self.agreement_type == AgreementType.EXTERNAL_LENDER and not self.partner_id:
            errors["partner"] = _("Select a financing partner for external lender agreements.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            original = FinanceAgreement.all_objects.get(pk=self.pk)
            if original.status in {
                AgreementStatus.ACTIVE,
                AgreementStatus.COMPLETED,
                AgreementStatus.DEFAULTED,
                AgreementStatus.CANCELLED,
            }:
                changed = [
                    field for field in self.protected_term_fields
                    if getattr(original, field) != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        _("Active agreement financial terms are immutable; create an amendment instead.")
                    )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse("financing:detail", kwargs={"pk": self.pk})


class Installment(TenantModel, ImmutableModel, CompanyConsistencyMixin):
    company_relations = ("agreement",)

    agreement = models.ForeignKey(
        FinanceAgreement,
        on_delete=models.PROTECT,
        related_name="installments",
        verbose_name=_("agreement"),
    )
    sequence = models.PositiveSmallIntegerField(_("installment number"))
    due_date = models.DateField(_("due date"))
    amount = models.DecimalField(_("scheduled amount"), max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["agreement", "sequence"], name="unique_installment_sequence_per_agreement"
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="installment_amount_positive"),
        ]

    def __str__(self):
        return f"{self.agreement.number} / {self.sequence}"


class PaymentAllocation(TenantModel, ImmutableModel, CompanyConsistencyMixin):
    company_relations = ("entry", "installment", "reversal_of")

    entry = models.ForeignKey(
        "payments.LedgerEntry",
        on_delete=models.PROTECT,
        related_name="installment_allocations",
        verbose_name=_("ledger entry"),
    )
    installment = models.ForeignKey(
        Installment,
        on_delete=models.PROTECT,
        related_name="allocations",
        verbose_name=_("installment"),
    )
    amount = models.DecimalField(_("allocated amount"), max_digits=14, decimal_places=2)
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
        related_name="installment_allocations",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_allocation_amount_positive"),
            models.UniqueConstraint(
                fields=["reversal_of"],
                condition=models.Q(reversal_of__isnull=False),
                name="one_reversal_per_payment_allocation",
            ),
        ]


class LenderDisbursement(TenantModel, ImmutableModel, CompanyConsistencyMixin):
    """Money an external financing partner paid to the dealership."""

    company_relations = ("agreement", "partner", "entry")
    agreement = models.ForeignKey(
        FinanceAgreement,
        on_delete=models.PROTECT,
        related_name="lender_disbursements",
        verbose_name=_("agreement"),
    )
    partner = models.ForeignKey(
        FinancingPartner,
        on_delete=models.PROTECT,
        related_name="disbursements",
        verbose_name=_("financing partner"),
    )
    entry = models.OneToOneField(
        "payments.LedgerEntry",
        on_delete=models.PROTECT,
        related_name="lender_disbursement",
        verbose_name=_("ledger entry"),
    )
    external_reference = models.CharField(_("external reference"), max_length=100, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)


class AgreementGuarantor(TenantModel, CompanyConsistencyMixin):
    company_relations = ("agreement",)

    agreement = models.ForeignKey(
        FinanceAgreement,
        on_delete=models.PROTECT,
        related_name="guarantors",
        verbose_name=_("agreement"),
    )
    full_name = models.CharField(_("full name"), max_length=200)
    national_id = models.CharField(_("national ID"), max_length=100, blank=True)
    phone = models.CharField(_("phone"), max_length=50)
    address = models.TextField(_("address"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    def __str__(self):
        return self.full_name


class AgreementEventType(models.TextChoices):
    CREATED = "created", _("Created")
    SUBMITTED = "submitted", _("Submitted for approval")
    ACTIVATED = "activated", _("Activated")
    PAYMENT = "payment", _("Payment recorded")
    COMPLETED = "completed", _("Completed")
    DEFAULTED = "defaulted", _("Defaulted")
    CANCELLED = "cancelled", _("Cancelled")


class AgreementEvent(TenantModel, ImmutableModel, CompanyConsistencyMixin):
    company_relations = ("agreement", "performed_by")

    agreement = models.ForeignKey(
        FinanceAgreement,
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name=_("agreement"),
    )
    event_type = models.CharField(_("event type"), max_length=30, choices=AgreementEventType.choices)
    description = models.CharField(_("description"), max_length=255, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="finance_agreement_events",
        verbose_name=_("performed by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class InstallmentReminder(TenantModel, ImmutableModel, CompanyConsistencyMixin):
    """Idempotency record: one reminder kind per installment and calendar day."""

    company_relations = ("installment",)
    installment = models.ForeignKey(
        Installment,
        on_delete=models.PROTECT,
        related_name="reminders",
        verbose_name=_("installment"),
    )
    kind = models.CharField(_("reminder kind"), max_length=30)
    reminder_date = models.DateField(_("reminder date"))
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["installment", "kind", "reminder_date"],
                name="unique_installment_reminder_per_day",
            )
        ]
