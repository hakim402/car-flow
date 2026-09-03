"""Expense writes flow through the general ledger (README §17).

The service is the integrity boundary: imports, shell code, future APIs, and
Celery jobs can all bypass the form, so monetary and tenant checks live here.
"""
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.core.validation import validate_same_company
from apps.payments.models import EntryType, LedgerEntry
from apps.payments.services import _positive_money, _validate_account


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
    amount = _positive_money(amount)
    if category is None:
        raise ValidationError({"category": _("Select an expense category.")})
    if account is None:
        raise ValidationError({"account": _("Select the financial account that paid this expense.")})
    validate_same_company(
        company,
        {"expense category": category, "financial account": account, "branch": branch},
    )
    if not category.active:
        raise ValidationError({"category": _("The selected expense category is inactive.")})
    _validate_account(account, company, currency)

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
