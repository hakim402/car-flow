"""Expenses have no model of their own (agent.md §6, §10 Step 7): an expense
is a ledger row of type `expense`, written through this single helper."""
from django.db import transaction

from apps.payments.models import EntryType, LedgerEntry


@transaction.atomic
def record_expense(company, amount, currency, description="", user=None) -> LedgerEntry:
    return LedgerEntry.objects.create(
        company=company,
        type=EntryType.EXPENSE,
        amount=amount,
        currency=currency,
        description=description,
        created_by=user if user and user.is_authenticated else None,
    )
