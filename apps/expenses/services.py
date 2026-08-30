"""Expense writes flow through the general ledger (agent.md §10 Step 7)."""
from datetime import date

from django.db import transaction

from apps.payments.models import EntryType, LedgerEntry


@transaction.atomic
def record_expense(
    company,
    amount,
    currency,
    description="",
    user=None,
    category=None,
    account=None,
    branch=None,
    vendor="",
    reference="",
    transaction_date=None,
) -> LedgerEntry:
    return LedgerEntry.objects.create(
        company=company,
        type=EntryType.EXPENSE,
        amount=amount,
        currency=currency,
        account=account,
        branch=branch,
        expense_category=category,
        vendor=vendor,
        transaction_date=transaction_date or date.today(),
        reference=reference,
        description=description,
        created_by=user if user and user.is_authenticated else None,
    )
