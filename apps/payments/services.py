"""Ledger write paths for payments (agent.md §6: everything writes through
the ledger; there is no other way to move money)."""
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from apps.communications import notification_engine
from apps.core.validation import validate_same_company

from .models import EntryType, LedgerEntry, LedgerSequence, PaymentMethod

logger = logging.getLogger(__name__)


def _positive_money(value, label="amount") -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({label: _("Enter a valid monetary amount.")})
    if amount <= 0:
        raise ValidationError({label: _("Amount must be greater than zero.")})
    return amount


def _validate_account(account, company, currency):
    if account is None:
        return
    validate_same_company(company, {"account": account})
    if not account.active:
        raise ValidationError({"account": _("The selected financial account is inactive.")})
    if account.currency != currency:
        raise ValidationError(
            {"currency": _("Payment currency must match the financial account currency.")}
        )


def next_receipt_number(company, transaction_date=None) -> str:
    """Return RCT-YYYY-NNNNNN using a row lock to avoid duplicate receipts."""
    transaction_date = transaction_date or date.today()
    year = transaction_date.year
    sequence = (
        LedgerSequence.all_objects.select_for_update()
        .filter(company=company, kind="receipt", year=year)
        .first()
    )
    if sequence is None:
        try:
            with transaction.atomic():
                sequence = LedgerSequence.all_objects.create(
                    company=company, kind="receipt", year=year, last_value=0
                )
        except IntegrityError:
            sequence = LedgerSequence.all_objects.select_for_update().get(
                company=company, kind="receipt", year=year
            )
    sequence.last_value += 1
    candidate = f"RCT-{year}-{sequence.last_value:06d}"
    while LedgerEntry.all_objects.filter(
        company=company, receipt_number=candidate
    ).exists():
        sequence.last_value += 1
        candidate = f"RCT-{year}-{sequence.last_value:06d}"
    sequence.save(update_fields=["last_value"])
    return candidate


@transaction.atomic
def record_payment(
    sale,
    amount,
    currency,
    user=None,
    description="",
    account=None,
    payment_method=None,
    transaction_date=None,
    reference="",
    receipt_number="",
) -> LedgerEntry:
    """Record a customer payment against a sale as one ledger row."""
    # Cross-tenant references must be impossible through the write path
    # (README §25.2): a payment belongs to the sale's customer and company.
    amount = _positive_money(amount)
    if currency != sale.currency:
        raise ValidationError({"currency": _("Payment currency must match the sale currency.")})
    validate_same_company(sale.company, {"sale customer": sale.customer})
    _validate_account(account, sale.company, currency)
    transaction_date = transaction_date or date.today()
    receipt_number = receipt_number or next_receipt_number(sale.company, transaction_date)
    if LedgerEntry.all_objects.filter(
        company=sale.company, receipt_number=receipt_number
    ).exists():
        raise ValidationError({"receipt_number": _("Receipt number already exists.")})
    entry = LedgerEntry.objects.create(
        company=sale.company,
        type=EntryType.CUSTOMER_PAYMENT,
        amount=amount,
        currency=currency,
        account=account,
        payment_method=payment_method or PaymentMethod.OTHER,
        transaction_date=transaction_date,
        description=description or f"{sale}",
        reference=reference,
        receipt_number=receipt_number,
        customer=sale.customer,
        sale=sale,
        content_type_id=_content_type_id(sale),
        object_id=sale.pk,
        created_by=user if user and user.is_authenticated else None,
    )
    # §7.2: the single approved way business code reaches messaging.
    def notify_after_commit():
        try:
            notification_engine.notify(
                "payment_recorded",
                company=sale.company,
                customer=sale.customer,
                context={"amount": amount, "currency": currency},
            )
        except Exception:  # notification must never break the ledger write
            logger.exception("payment_recorded notification failed")

    transaction.on_commit(notify_after_commit)
    return entry


@transaction.atomic
def record_supplier_payment(
    supplier,
    amount,
    currency,
    user=None,
    description="",
    purchase_order=None,
    account=None,
    payment_method=None,
    transaction_date=None,
    reference="",
    receipt_number="",
) -> LedgerEntry:
    """Record money paid OUT to a supplier (import invoices, deposits) as
    one ledger row pointing at the supplier."""
    amount = _positive_money(amount)
    validate_same_company(supplier.company, {"purchase_order": purchase_order})
    _validate_account(account, supplier.company, currency)
    if purchase_order is not None and currency not in purchase_order.total_by_currency():
        raise ValidationError(
            {"currency": _("Payment currency must match a currency used by the purchase order.")}
        )
    transaction_date = transaction_date or date.today()
    receipt_number = receipt_number or next_receipt_number(supplier.company, transaction_date)
    if LedgerEntry.all_objects.filter(
        company=supplier.company, receipt_number=receipt_number
    ).exists():
        raise ValidationError({"receipt_number": _("Receipt number already exists.")})
    return LedgerEntry.objects.create(
        company=supplier.company,
        type=EntryType.SUPPLIER_PAYMENT,
        amount=amount,
        currency=currency,
        account=account,
        payment_method=payment_method or PaymentMethod.OTHER,
        transaction_date=transaction_date,
        description=description or f"{supplier}",
        reference=reference,
        receipt_number=receipt_number,
        supplier=supplier,
        purchase_order=purchase_order,
        content_type_id=_content_type_id(supplier),
        object_id=supplier.pk,
        created_by=user if user and user.is_authenticated else None,
    )


@transaction.atomic
def reverse_entry(entry: LedgerEntry, user=None, description="") -> LedgerEntry:
    """Correct a ledger row by appending its mirror image (§6: never edit).

    Rules (README §16): an original entry can be reversed at most once, a
    reversal cannot itself be reversed, and the database uniqueness on
    `reversal_of` protects the race between two simultaneous corrections."""
    if entry.reversal_of_id is not None:
        raise ValidationError(_("A reversal cannot be reversed."))
    if entry.reversals.exists():
        raise ValidationError(_("This entry has already been reversed."))
    try:
        return LedgerEntry.objects.create(
            company=entry.company,
            type=entry.type,
            amount=entry.amount,
            currency=entry.currency,
            account=entry.account,
            payment_method=entry.payment_method,
            transaction_date=date.today(),
            description=description or f"Reversal of {entry.pk}",
            reference=entry.reference,
            receipt_number=next_receipt_number(entry.company),
            branch=entry.branch,
            customer=entry.customer,
            sale=entry.sale,
            reservation=entry.reservation,
            purchase_order=entry.purchase_order,
            supplier=entry.supplier,
            expense_category=entry.expense_category,
            vendor=entry.vendor,
            content_type=entry.content_type,
            object_id=entry.object_id,
            reversal_of=entry,
            created_by=user if user and user.is_authenticated else None,
        )
    except IntegrityError:
        # Concurrent reversal lost the race against the unique constraint;
        # surface it as a business error, not a 500.
        raise ValidationError(_("This entry has already been reversed."))


def _content_type_id(instance):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(instance).pk
