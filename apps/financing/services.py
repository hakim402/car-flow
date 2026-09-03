"""Transactional financing workflows and computed installment balances."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounting.services import sale_outstanding, sale_payments
from apps.payments.services import record_payment
from apps.sales.models import SaleStatus

from .models import (
    AgreementEvent,
    AgreementEventType,
    AgreementStatus,
    AgreementType,
    FinanceAgreement,
    Installment,
    LenderDisbursement,
    PaymentAllocation,
    PaymentFrequency,
)

CENT = Decimal("0.01")


def new_agreement_number() -> str:
    return f"FIN-{timezone.localdate().year}-{uuid4().hex[:8].upper()}"


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def due_date_for(agreement: FinanceAgreement, index: int) -> date:
    if agreement.frequency == PaymentFrequency.WEEKLY:
        return agreement.first_due_date + timedelta(days=7 * index)
    if agreement.frequency == PaymentFrequency.BIWEEKLY:
        return agreement.first_due_date + timedelta(days=14 * index)
    return _add_months(agreement.first_due_date, index)


def schedule_preview(agreement: FinanceAgreement) -> list[dict]:
    """Build an exact schedule; rounding remainder goes to the final line."""
    if agreement.installment_count <= 0 or agreement.amount_financed <= 0:
        return []
    regular = (
        agreement.amount_financed / agreement.installment_count
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    rows = []
    allocated = Decimal("0")
    for index in range(agreement.installment_count):
        amount = regular
        if index == agreement.installment_count - 1:
            amount = agreement.amount_financed - allocated
        amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        rows.append(
            {"sequence": index + 1, "due_date": due_date_for(agreement, index), "amount": amount}
        )
        allocated += amount
    return rows


def _event(agreement, event_type, user=None, description=""):
    return AgreementEvent.objects.create(
        company=agreement.company,
        agreement=agreement,
        event_type=event_type,
        description=description,
        performed_by=user if user and user.is_authenticated else None,
    )


@transaction.atomic
def initialize_agreement(agreement: FinanceAgreement, user=None) -> FinanceAgreement:
    agreement.number = agreement.number or new_agreement_number()
    agreement.created_by = user if user and user.is_authenticated else None
    agreement.customer_snapshot = {
        "full_name": agreement.sale.customer.full_name,
        "phone": agreement.sale.customer.phone,
        "email": agreement.sale.customer.email,
        "national_id": agreement.sale.customer.national_id,
    }
    agreement.vehicle_snapshot = {
        "vin": agreement.sale.vehicle.vin,
        "make": agreement.sale.vehicle.make,
        "model": agreement.sale.vehicle.model,
        "year": agreement.sale.vehicle.year,
        "color": agreement.sale.vehicle.color,
    }
    agreement.full_clean()
    agreement.save()
    _event(agreement, AgreementEventType.CREATED, user)
    return agreement


@transaction.atomic
def submit_agreement(agreement: FinanceAgreement, user=None) -> FinanceAgreement:
    agreement = FinanceAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status != AgreementStatus.DRAFT:
        raise ValidationError(_("Only draft agreements can be submitted for approval."))
    agreement.full_clean()
    agreement.status = AgreementStatus.PENDING_APPROVAL
    agreement.save(update_fields=["status", "updated_at"])
    _event(agreement, AgreementEventType.SUBMITTED, user)
    return agreement


def _down_payment_received(agreement: FinanceAgreement) -> Decimal:
    paid = sale_payments(agreement.sale).get(agreement.currency, Decimal("0"))
    return max(paid, Decimal("0"))


@transaction.atomic
def approve_agreement(agreement: FinanceAgreement, user=None) -> FinanceAgreement:
    """Activate terms and atomically create the immutable payment schedule."""
    agreement = FinanceAgreement.objects.select_for_update().select_related(
        "sale", "sale__customer", "sale__vehicle"
    ).get(pk=agreement.pk)
    if agreement.status != AgreementStatus.PENDING_APPROVAL:
        raise ValidationError(_("Only pending agreements can be approved."))
    if agreement.sale.status != SaleStatus.COMPLETED:
        raise ValidationError(_("Complete the vehicle sale before activating financing."))
    if _down_payment_received(agreement) < agreement.down_payment_required:
        raise ValidationError(_("Record the required down payment before activating financing."))
    agreement.full_clean()
    rows = schedule_preview(agreement)
    if not rows or sum(row["amount"] for row in rows) != agreement.amount_financed:
        raise ValidationError(_("The installment schedule does not match the financed amount."))
    if agreement.installments.exists():
        raise ValidationError(_("This agreement already has an installment schedule."))
    Installment.all_objects.bulk_create(
        [
            Installment(
                company=agreement.company,
                agreement=agreement,
                sequence=row["sequence"],
                due_date=row["due_date"],
                amount=row["amount"],
            )
            for row in rows
        ]
    )
    now = timezone.now()
    agreement.status = AgreementStatus.ACTIVE
    agreement.approved_by = user if user and user.is_authenticated else None
    agreement.approved_at = now
    agreement.activated_at = now
    agreement.save(
        update_fields=["status", "approved_by", "approved_at", "activated_at", "updated_at"]
    )
    _event(agreement, AgreementEventType.ACTIVATED, user)
    return agreement


def installment_paid(installment: Installment) -> Decimal:
    total = Decimal("0")
    allocations = installment.allocations.select_related("entry", "reversal_of").prefetch_related(
        "entry__reversals"
    )
    for allocation in allocations:
        # A reversed cash receipt has no economic effect on the schedule.
        if allocation.entry.reversals.exists():
            continue
        total += -allocation.amount if allocation.reversal_of_id else allocation.amount
    return max(total, Decimal("0"))


def installment_summary(installment: Installment, as_of=None) -> dict:
    as_of = as_of or timezone.localdate()
    paid = installment_paid(installment)
    outstanding = max(installment.amount - paid, Decimal("0"))
    grace_due = installment.due_date + timedelta(days=installment.agreement.grace_days)
    if outstanding == 0:
        status = "paid"
    elif paid > 0:
        status = "overdue" if grace_due < as_of else "partial"
    elif grace_due < as_of:
        status = "overdue"
    elif installment.due_date <= as_of:
        status = "due"
    else:
        status = "upcoming"
    return {
        "paid": paid,
        "outstanding": outstanding,
        "status": status,
        "days_overdue": max((as_of - grace_due).days, 0) if outstanding else 0,
    }


def agreement_summary(agreement: FinanceAgreement, as_of=None) -> dict:
    as_of = as_of or timezone.localdate()
    scheduled = Decimal("0")
    paid = Decimal("0")
    overdue = Decimal("0")
    next_due = None
    rows = []
    for installment in agreement.installments.all():
        item = installment_summary(installment, as_of)
        scheduled += installment.amount
        paid += item["paid"]
        if item["status"] == "overdue":
            overdue += item["outstanding"]
        if item["outstanding"] > 0 and next_due is None:
            next_due = installment.due_date
        rows.append((installment, item))
    if not rows and agreement.status in {
        AgreementStatus.DRAFT,
        AgreementStatus.PENDING_APPROVAL,
    }:
        scheduled = agreement.amount_financed
    if agreement.agreement_type == AgreementType.EXTERNAL_LENDER and agreement.status in {
        AgreementStatus.ACTIVE,
        AgreementStatus.COMPLETED,
    }:
        dealership_outstanding = max(
            sale_outstanding(agreement.sale).get(agreement.currency, Decimal("0")),
            Decimal("0"),
        )
        scheduled = agreement.amount_financed
        paid = max(scheduled - dealership_outstanding, Decimal("0"))
        overdue = Decimal("0")
        next_due = None
    return {
        "scheduled": scheduled,
        "paid": paid,
        "outstanding": max(scheduled - paid, Decimal("0")),
        "overdue": overdue,
        "next_due": next_due,
        "down_payment_received": _down_payment_received(agreement),
        "rows": rows,
    }


@transaction.atomic
def record_installment_payment(
    agreement: FinanceAgreement,
    amount,
    account,
    user=None,
    payment_method=None,
    transaction_date=None,
    reference="",
    description="",
):
    agreement = FinanceAgreement.objects.select_for_update().select_related(
        "sale", "sale__customer"
    ).get(pk=agreement.pk)
    if agreement.agreement_type != AgreementType.DEALER_INSTALLMENT:
        raise ValidationError(_("Payments for external lender agreements are collected by the lender."))
    if agreement.status not in {AgreementStatus.ACTIVE, AgreementStatus.DEFAULTED}:
        raise ValidationError(_("Payments can only be recorded for active or defaulted agreements."))
    if account is None:
        raise ValidationError(_("Select the financial account receiving this payment."))
    try:
        amount = Decimal(amount)
    except Exception:
        raise ValidationError(_("Enter a valid payment amount."))
    if amount <= 0:
        raise ValidationError(_("Payment amount must be greater than zero."))
    summary = agreement_summary(agreement)
    if amount > summary["outstanding"]:
        raise ValidationError(_("Payment exceeds the agreement's outstanding balance."))
    entry = record_payment(
        agreement.sale,
        amount,
        agreement.currency,
        user=user,
        description=description or f"Installment payment — {agreement.number}",
        account=account,
        payment_method=payment_method,
        transaction_date=transaction_date,
        reference=reference,
    )
    remaining = amount
    installments = list(
        Installment.objects.select_for_update().filter(agreement=agreement).order_by("due_date", "sequence")
    )
    for installment in installments:
        due = installment_summary(installment)["outstanding"]
        if due <= 0:
            continue
        allocated = min(remaining, due)
        PaymentAllocation.objects.create(
            company=agreement.company,
            entry=entry,
            installment=installment,
            amount=allocated,
            created_by=user if user and user.is_authenticated else None,
        )
        remaining -= allocated
        if remaining == 0:
            break
    if remaining != 0:
        raise ValidationError(_("The payment could not be fully allocated."))
    _event(
        agreement,
        AgreementEventType.PAYMENT,
        user,
        _("Receipt %(receipt)s") % {"receipt": entry.receipt_number},
    )
    if agreement_summary(agreement)["outstanding"] == 0:
        agreement.status = AgreementStatus.COMPLETED
        agreement.completed_at = timezone.now()
        agreement.save(update_fields=["status", "completed_at", "updated_at"])
        _event(agreement, AgreementEventType.COMPLETED, user)
    return entry


@transaction.atomic
def record_lender_disbursement(
    agreement: FinanceAgreement,
    amount,
    account,
    user=None,
    payment_method=None,
    transaction_date=None,
    reference="",
    description="",
):
    # Lock only the agreement row. ``partner`` is nullable, so PostgreSQL
    # renders that select_related() as an outer join and rejects a blanket
    # FOR UPDATE lock on the nullable side of the join.
    agreement = FinanceAgreement.objects.select_for_update(of=("self",)).select_related(
        "sale", "sale__customer", "partner"
    ).get(pk=agreement.pk)
    if agreement.agreement_type != AgreementType.EXTERNAL_LENDER or agreement.partner is None:
        raise ValidationError(_("This agreement is not connected to an external lender."))
    if agreement.status != AgreementStatus.ACTIVE:
        raise ValidationError(_("Lender disbursements require an active agreement."))
    if account is None:
        raise ValidationError(_("Select the financial account receiving this payment."))
    try:
        amount = Decimal(amount)
    except Exception:
        raise ValidationError(_("Enter a valid payment amount."))
    outstanding = sale_outstanding(agreement.sale).get(agreement.currency, Decimal("0"))
    if amount <= 0 or amount > outstanding:
        raise ValidationError(_("Disbursement must be positive and cannot exceed the sale balance."))
    entry = record_payment(
        agreement.sale,
        amount,
        agreement.currency,
        user=user,
        description=description or f"Lender disbursement — {agreement.partner.name}",
        account=account,
        payment_method=payment_method,
        transaction_date=transaction_date,
        reference=reference or agreement.external_reference,
    )
    LenderDisbursement.objects.create(
        company=agreement.company,
        agreement=agreement,
        partner=agreement.partner,
        entry=entry,
        external_reference=reference or agreement.external_reference,
    )
    if sale_outstanding(agreement.sale).get(agreement.currency, Decimal("0")) <= 0:
        agreement.status = AgreementStatus.COMPLETED
        agreement.completed_at = timezone.now()
        agreement.save(update_fields=["status", "completed_at", "updated_at"])
        _event(agreement, AgreementEventType.COMPLETED, user, _("Lender funded the sale in full."))
    return entry


@transaction.atomic
def mark_defaulted(agreement: FinanceAgreement, user=None, description=""):
    agreement = FinanceAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.agreement_type != AgreementType.DEALER_INSTALLMENT:
        raise ValidationError(_("External lender agreements are managed by the lender."))
    if agreement.status != AgreementStatus.ACTIVE:
        raise ValidationError(_("Only active agreements can be marked defaulted."))
    if agreement_summary(agreement)["overdue"] <= 0:
        raise ValidationError(_("An agreement without overdue installments cannot be defaulted."))
    agreement.status = AgreementStatus.DEFAULTED
    agreement.save(update_fields=["status", "updated_at"])
    _event(agreement, AgreementEventType.DEFAULTED, user, description)
    return agreement


@transaction.atomic
def cancel_agreement(agreement: FinanceAgreement, user=None, description=""):
    agreement = FinanceAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status not in {AgreementStatus.DRAFT, AgreementStatus.PENDING_APPROVAL}:
        raise ValidationError(_("Only draft or pending agreements can be cancelled."))
    agreement.status = AgreementStatus.CANCELLED
    agreement.save(update_fields=["status", "updated_at"])
    _event(agreement, AgreementEventType.CANCELLED, user, description)
    return agreement
