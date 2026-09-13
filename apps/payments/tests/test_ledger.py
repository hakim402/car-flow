"""Ledger gate (agent.md §6, §10 Step 12).

Guarantees under test:
- rows are append-only: UPDATE/DELETE raise at the model level;
- corrections are mirror rows with `reversal_of`, and aggregates net them;
- computed state (balances, outstanding) always matches the rows.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.services import (
    ledger_balance,
    money_in,
    money_out,
    sale_outstanding,
    sale_payment_summary,
    sale_payments,
)
from apps.core.models import ImmutableRecordError
from apps.core.tenancy import company_scope
from apps.core.testing import CustomerFactory, SaleFactory, VehicleFactory
from apps.payments.models import EntryType, FinancialAccount, LedgerEntry
from apps.payments.services import record_payment, record_reservation_payment, reverse_entry
from apps.sales.models import Reservation

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
    # The fail-closed tenant manager needs explicit context (§25.1).
    with company_scope(company):
        return LedgerEntry.objects.create(**defaults)


def _account(company, currency="USD"):
    return FinancialAccount.objects.create(
        company=company,
        name=f"Test {currency} cashbox",
        currency=currency,
        active=True,
    )


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
        account = _account(sale.company)
        entry = record_payment(sale, Decimal("5000.00"), "USD", account=account)
        assert ledger_balance()["USD"] == Decimal("5000.00")

        reversal = reverse_entry(entry, description="Customer payment correction")
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
        reverse_entry(expense, description="Expense entered in error")
        assert money_out().get("AFN", ZERO) == ZERO
        assert money_in().get("AFN", ZERO) == ZERO
        assert ledger_balance().get("AFN", ZERO) == ZERO


@pytest.mark.django_db
def test_sale_outstanding_matches_rows(sale):
    with company_scope(sale.company):
        account = _account(sale.company)
        entry = record_payment(sale, Decimal("5000.00"), "USD", account=account)
        assert sale_payments(sale)["USD"] == Decimal("5000.00")
        assert sale_outstanding(sale)["USD"] == Decimal("10000.00")

        # Reverse the whole payment, then record a smaller one: the
        # aggregates must follow the rows, not the history.
        reverse_entry(entry, description="Replace incorrect payment")
        record_payment(sale, Decimal("3000.00"), "USD", account=account)
        assert sale_payments(sale)["USD"] == Decimal("3000.00")
        assert sale_outstanding(sale)["USD"] == Decimal("12000.00")


@pytest.mark.django_db
def test_two_dollar_balance_remains_a_partial_customer_debt(sale):
    sale.agreed_amount = Decimal("100.00")
    sale.save(update_fields=["agreed_amount", "updated_at"])
    with company_scope(sale.company):
        account = _account(sale.company)
        record_payment(sale, Decimal("98.00"), "USD", account=account)
        summary = sale_payment_summary(sale)

    assert summary["paid"] == Decimal("98.00")
    assert summary["outstanding"] == Decimal("2.00")
    assert summary["status"] == "partial"


@pytest.mark.django_db
def test_customer_payment_cannot_create_an_untracked_credit(sale):
    with company_scope(sale.company):
        account = _account(sale.company)
        with pytest.raises(ValidationError, match="outstanding balance"):
            record_payment(sale, Decimal("15000.01"), "USD", account=account)


@pytest.mark.django_db
def test_payment_uses_financial_account_branch_for_reporting(sale):
    with company_scope(sale.company):
        account = _account(sale.company)
        entry = record_payment(sale, Decimal("100.00"), "USD", account=account)
    assert entry.branch_id == account.branch_id


@pytest.mark.django_db
def test_balance_ignores_other_tenants(sale):
    other_sale = SaleFactory()
    _entry(other_sale.company, amount=Decimal("9999.00"))

    with company_scope(sale.company):
        assert ledger_balance() == {}


@pytest.mark.django_db
def test_payment_rejects_currency_mismatch_and_reversal_preserves_references(sale):
    with company_scope(sale.company):
        account = _account(sale.company)
        with pytest.raises(Exception, match="sale currency"):
            record_payment(sale, Decimal("50.00"), "AFN", account=account)
        entry = record_payment(
            sale, Decimal("50.00"), "USD", account=account, reference="TRANSFER-1"
        )
        reversal = reverse_entry(entry, description="Duplicate bank transfer")
        assert reversal.sale_id == sale.pk
        assert reversal.customer_id == sale.customer_id
        assert reversal.reference == "TRANSFER-1"
        assert reversal.receipt_number.startswith("RCT-")


@pytest.mark.django_db
def test_reservation_deposit_is_carried_into_linked_sale_without_duplication(sale):
    company = sale.company
    customer = CustomerFactory(company=company)
    vehicle = VehicleFactory(company=company)
    with company_scope(company):
        account = _account(company)
        reservation = Reservation.objects.create(
            company=company,
            customer=customer,
            vehicle=vehicle,
            deposit_amount=Decimal("500.00"),
            currency="USD",
        )
        entry = record_reservation_payment(
            reservation, Decimal("200.00"), "USD", account=account
        )
        linked_sale = SaleFactory(
            company=company,
            customer=customer,
            vehicle=vehicle,
            reservation=reservation,
            agreed_amount=Decimal("1000.00"),
            currency="USD",
        )
        summary = sale_payment_summary(linked_sale)

    assert entry.reservation_id == reservation.pk
    assert entry.sale_id is None
    assert summary["paid"] == Decimal("200.00")
    assert summary["outstanding"] == Decimal("800.00")
