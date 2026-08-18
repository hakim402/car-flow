"""Ledger gate (agent.md §6, §10 Step 12).

Guarantees under test:
- rows are append-only: UPDATE/DELETE raise at the model level;
- corrections are mirror rows with `reversal_of`, and aggregates net them;
- computed state (balances, outstanding) always matches the rows.
"""
from decimal import Decimal

import pytest

from apps.accounting.services import (
    ledger_balance,
    money_in,
    money_out,
    sale_outstanding,
    sale_payments,
)
from apps.core.models import ImmutableRecordError
from apps.core.tenancy import company_scope
from apps.core.testing import SaleFactory
from apps.payments.models import EntryType, LedgerEntry
from apps.payments.services import record_payment, reverse_entry

ZERO = Decimal("0.00")


@pytest.fixture
def sale(db):
    return SaleFactory(agreed_amount=Decimal("15000.00"), currency="USD")


def _entry(company, **kwargs):
    defaults = dict(
        company=company,
        type=EntryType.CUSTOMER_PAYMENT,
        amount=Decimal("100.00"),
        currency="USD",
    )
    defaults.update(kwargs)
    return LedgerEntry.objects.create(**defaults)


@pytest.mark.django_db
def test_update_is_blocked(sale):
    entry = _entry(sale.company)
    entry.description = "tampered"
    with pytest.raises(ImmutableRecordError):
        entry.save()


@pytest.mark.django_db
def test_delete_is_blocked(sale):
    entry = _entry(sale.company)
    with pytest.raises(ImmutableRecordError):
        entry.delete()


@pytest.mark.django_db
def test_reversal_math_nets_to_zero(sale):
    with company_scope(sale.company):
        entry = record_payment(sale, Decimal("5000.00"), "USD")
        assert ledger_balance()["USD"] == Decimal("5000.00")

        reversal = reverse_entry(entry)
        assert reversal.reversal_of_id == entry.pk
        assert ledger_balance()["USD"] == ZERO
        assert money_in()["USD"] == ZERO


@pytest.mark.django_db
def test_direction_and_money_out(sale):
    with company_scope(sale.company):
        _entry(sale.company, type=EntryType.EXPENSE, amount=Decimal("200.00"), currency="AFN")
        _entry(sale.company, amount=Decimal("300.00"), currency="AFN")

        assert money_out()["AFN"] == Decimal("200.00")
        assert money_in()["AFN"] == Decimal("300.00")
        assert ledger_balance()["AFN"] == Decimal("100.00")


@pytest.mark.django_db
def test_expense_reversal_reduces_money_out(sale):
    """Regression: a reversal row inherits the original's type, so it must
    cancel money_out — not double-count it as money in."""
    with company_scope(sale.company):
        expense = _entry(
            sale.company, type=EntryType.EXPENSE, amount=Decimal("250.00"), currency="AFN"
        )
        reverse_entry(expense)
        assert money_out().get("AFN", ZERO) == ZERO
        assert money_in().get("AFN", ZERO) == ZERO
        assert ledger_balance().get("AFN", ZERO) == ZERO


@pytest.mark.django_db
def test_sale_outstanding_matches_rows(sale):
    with company_scope(sale.company):
        entry = record_payment(sale, Decimal("5000.00"), "USD")
        assert sale_payments(sale)["USD"] == Decimal("5000.00")
        assert sale_outstanding(sale)["USD"] == Decimal("10000.00")

        # Reverse the whole payment, then record a smaller one: the
        # aggregates must follow the rows, not the history.
        reverse_entry(entry)
        record_payment(sale, Decimal("3000.00"), "USD")
        assert sale_payments(sale)["USD"] == Decimal("3000.00")
        assert sale_outstanding(sale)["USD"] == Decimal("12000.00")


@pytest.mark.django_db
def test_balance_ignores_other_tenants(sale):
    other_sale = SaleFactory()
    _entry(other_sale.company, amount=Decimal("9999.00"))

    with company_scope(sale.company):
        assert ledger_balance() == {}
