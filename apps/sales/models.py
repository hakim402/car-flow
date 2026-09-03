"""Sales pipeline models (agent.md §10 Step 6):
lead → quotation → reservation → sale → invoice.

- Monetary fields always carry an explicit `currency` (§9).
- `Invoice` is immutable (§6): corrections are new rows handled later via the
  ledger, never edits to an issued invoice.
- Current-state values are computed over rows, never stored.
"""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.models import CompanyConsistencyMixin, ImmutableModel
from apps.core.tenancy import TenantModel


class LeadSource(models.TextChoices):
    WALK_IN = "walk_in", _("Walk-in")
    PHONE = "phone", _("Phone call")
    WHATSAPP = "whatsapp", _("WhatsApp")
    REFERRAL = "referral", _("Referral")
    OTHER = "other", _("Other")


class LeadStatus(models.TextChoices):
    NEW = "new", _("New")
    CONTACTED = "contacted", _("Contacted")
    QUALIFIED = "qualified", _("Qualified")
    CONVERTED = "converted", _("Converted")
    LOST = "lost", _("Lost")


class LeadLostReason(models.TextChoices):
    PRICE_TOO_HIGH = "price_too_high", _("Price too high")
    BOUGHT_ELSEWHERE = "bought_elsewhere", _("Bought elsewhere")
    NO_RESPONSE = "no_response", _("No response")
    FINANCING = "financing", _("Financing")
    VEHICLE_UNAVAILABLE = "vehicle_unavailable", _("Vehicle unavailable")
    CHANGED_MIND = "changed_mind", _("Changed mind")
    OTHER = "other", _("Other")


class Lead(TenantModel, CompanyConsistencyMixin):
    company_relations = ("customer", "vehicle_of_interest", "branch", "assigned_to")

    name = models.CharField(_("name"), max_length=200, help_text=_("Lead or prospect name."))
    phone = models.CharField(
        _("phone"),
        max_length=50,
        blank=True,
        help_text=_("Best phone number or WhatsApp contact for this lead."),
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="leads",
        verbose_name=_("customer"),
        null=True,
        blank=True,
    )
    vehicle_of_interest = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.SET_NULL,
        related_name="interested_leads",
        verbose_name=_("vehicle of interest"),
        null=True,
        blank=True,
    )
    source = models.CharField(
        _("source"), max_length=20, choices=LeadSource.choices, default=LeadSource.WALK_IN
    )
    status = models.CharField(
        _("status"), max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="leads",
        verbose_name=_("branch"),
        null=True,
        blank=True,
        help_text=_("Branch where this lead was captured or is being managed."),
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_leads",
        verbose_name=_("assigned to"),
        null=True,
        blank=True,
        help_text=_("Salesperson or team member handling follow-up."),
    )
    lost_reason = models.CharField(
        _("lost reason"),
        max_length=30,
        choices=LeadLostReason.choices,
        blank=True,
        help_text=_("Reason the opportunity was closed as lost."),
    )
    notes = models.TextField(
        _("notes"),
        blank=True,
        help_text=_("Lead notes, follow-up summary, and key buying intent details."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_leads",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("lead")
        verbose_name_plural = _("leads")
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("sales:lead_detail", kwargs={"pk": self.pk})


class QuotationStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    ACCEPTED = "accepted", _("Accepted")
    DECLINED = "declined", _("Declined")
    EXPIRED = "expired", _("Expired")


class Quotation(TenantModel, CompanyConsistencyMixin):
    company_relations = ("customer", "vehicle", "lead")

    number = models.CharField(
        _("quotation number"),
        max_length=50,
        blank=True,
        help_text=_("Unique quotation reference, for example QT-2026-000123."),
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="quotations",
        verbose_name=_("customer"),
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="quotations",
        verbose_name=_("vehicle"),
        null=True,
        blank=True,
    )
    lead = models.ForeignKey(
        Lead,
        on_delete=models.SET_NULL,
        related_name="quotations",
        verbose_name=_("lead"),
        null=True,
        blank=True,
    )
    amount = models.DecimalField(
        _("amount"),
        max_digits=14,
        decimal_places=2,
        help_text=_("Quoted selling price in the selected currency."),
    )
    currency = models.CharField(
        _("currency"),
        max_length=3,
        choices=CURRENCIES,
        default=DEFAULT_CURRENCY,
        help_text=_("Currency used for the quotation and any linked reservation."),
    )
    valid_until = models.DateField(_("valid until"), help_text=_("Deadline for acceptance of this quote."))
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=QuotationStatus.choices,
        default=QuotationStatus.DRAFT,
        help_text=_("Commercial status of this quotation."),
    )
    notes = models.TextField(
        _("notes"),
        blank=True,
        help_text=_("Terms, customer preferences, or negotiation details for this quote."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_quotations",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("quotation")
        verbose_name_plural = _("quotations")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{_('Quotation')} #{self.pk}"

    def get_absolute_url(self):
        return reverse("sales:quotation_detail", kwargs={"pk": self.pk})


class ReservationStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")
    EXPIRED = "expired", _("Expired")


class Reservation(TenantModel, CompanyConsistencyMixin):
    company_relations = ("customer", "vehicle", "quotation")

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="reservations",
        verbose_name=_("customer"),
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="reservations",
        verbose_name=_("vehicle"),
    )
    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.PROTECT,
        related_name="reservations",
        verbose_name=_("quotation"),
        null=True,
        blank=True,
    )
    deposit_amount = models.DecimalField(
        _("deposit amount"),
        max_digits=14,
        decimal_places=2,
        help_text=_("Temporary hold amount requested from the customer."),
    )
    currency = models.CharField(
        _("currency"),
        max_length=3,
        choices=CURRENCIES,
        default=DEFAULT_CURRENCY,
        help_text=_("Currency of the reservation deposit and vehicle value."),
    )
    expires_at = models.DateTimeField(
        _("expires at"),
        null=True,
        blank=True,
        help_text=_("When this reservation expires and the stock is released automatically."),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=ReservationStatus.choices,
        default=ReservationStatus.ACTIVE,
        help_text=_("Current state of the reservation."),
    )
    notes = models.TextField(
        _("notes"),
        blank=True,
        help_text=_("Reservation terms, conditions, or internal notes."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_reservations",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("reservation")
        verbose_name_plural = _("reservations")
        ordering = ["-created_at"]
        constraints = [
            # At most one ACTIVE reservation per vehicle, at the database
            # level (README §28): two racing requests cannot double-reserve.
            models.UniqueConstraint(
                fields=["vehicle"],
                condition=models.Q(status=ReservationStatus.ACTIVE),
                name="one_active_reservation_per_vehicle",
            ),
        ]

    @property
    def required_deposit_amount(self):
        return self.deposit_amount

    @required_deposit_amount.setter
    def required_deposit_amount(self, value):
        self.deposit_amount = value

    def __str__(self):
        return f"{_('Reservation')} #{self.pk} — {self.vehicle}"

    def get_absolute_url(self):
        return reverse("sales:reservation_list")


class SaleStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class Sale(TenantModel, CompanyConsistencyMixin):
    company_relations = ("customer", "vehicle", "reservation")

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="sales",
        verbose_name=_("customer"),
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="sales",
        verbose_name=_("vehicle"),
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name="sales",
        verbose_name=_("reservation"),
        null=True,
        blank=True,
    )
    agreed_amount = models.DecimalField(_("agreed amount"), max_digits=14, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, choices=CURRENCIES, default=DEFAULT_CURRENCY)
    sale_date = models.DateField(_("sale date"))
    status = models.CharField(
        _("status"), max_length=20, choices=SaleStatus.choices, default=SaleStatus.DRAFT
    )
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_sales",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("sale")
        verbose_name_plural = _("sales")
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        errors = {}
        if self.reservation_id:
            if self.reservation.customer_id != self.customer_id:
                errors["customer"] = _("Sale customer must match the reservation customer.")
            if self.reservation.vehicle_id != self.vehicle_id:
                errors["vehicle"] = _("Sale vehicle must match the reserved vehicle.")
            if self.reservation.currency != self.currency:
                errors["currency"] = _("Sale currency must match the reservation currency.")
        if (
            self.status == SaleStatus.COMPLETED
            and self.vehicle_id
            and Sale.all_objects.filter(
                vehicle_id=self.vehicle_id,
                status=SaleStatus.COMPLETED,
            ).exclude(pk=self.pk).exists()
        ):
            errors["vehicle"] = _("This vehicle already has a completed sale.")
        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    def __str__(self):
        return f"{_('Sale')} #{self.pk} — {self.vehicle}"

    def get_absolute_url(self):
        return reverse("sales:sale_detail", kwargs={"pk": self.pk})


class Invoice(TenantModel, ImmutableModel, CompanyConsistencyMixin):
    """An issued invoice is a financial document: append-only (§6)."""

    company_relations = ("sale",)

    sale = models.ForeignKey(
        Sale,
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name=_("sale"),
    )
    number = models.CharField(_("invoice number"), max_length=50)
    issued_on = models.DateField(_("issued on"))
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, choices=CURRENCIES, default=DEFAULT_CURRENCY)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invoices",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("invoice")
        verbose_name_plural = _("invoices")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="unique_invoice_number_per_company"),
            # One invoice per sale, enforced by the database (README §28):
            # issue_invoice() stays idempotent under concurrency.
            models.UniqueConstraint(fields=["sale"], name="unique_invoice_per_sale"),
            # Money rows are positive (README §28).
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="invoice_amount_positive"),
        ]

    def __str__(self):
        return self.number
