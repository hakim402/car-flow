"""Ledger write paths for payments (agent.md §6: everything writes through
the ledger; there is no other way to move money)."""
import logging

from django.db import transaction

from apps.communications import notification_engine

from .models import EntryType, LedgerEntry

logger = logging.getLogger(__name__)


@transaction.atomic
def record_payment(sale, amount, currency, user=None, description="") -> LedgerEntry:
    """Record a customer payment against a sale as one ledger row."""
    entry = LedgerEntry.objects.create(
        company=sale.company,
        type=EntryType.CUSTOMER_PAYMENT,
        amount=amount,
        currency=currency,
        description=description or f"{sale}",
        content_type_id=_content_type_id(sale),
        object_id=sale.pk,
        created_by=user if user and user.is_authenticated else None,
    )
    # §7.2: the single approved way business code reaches messaging.
    try:
        notification_engine.notify(
            "payment_recorded",
            company=sale.company,
            customer=sale.customer,
            context={"amount": amount, "currency": currency},
        )
    except Exception:  # notification must never break the ledger write
        logger.exception("payment_recorded notification failed")
    return entry


@transaction.atomic
def reverse_entry(entry: LedgerEntry, user=None, description="") -> LedgerEntry:
    """Correct a ledger row by appending its mirror image (§6: never edit)."""
    return LedgerEntry.objects.create(
        company=entry.company,
        type=entry.type,
        amount=entry.amount,
        currency=entry.currency,
        description=description or f"Reversal of {entry.pk}",
        content_type=entry.content_type,
        object_id=entry.object_id,
        reversal_of=entry,
        created_by=user if user and user.is_authenticated else None,
    )


def _content_type_id(instance):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(instance).pk
