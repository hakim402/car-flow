from datetime import date
from decimal import Decimal

import pytest

from apps.core.tenancy import company_scope
from apps.core.testing import SaleFactory, UserFactory
from apps.expenses.forms import ExpenseForm
from apps.payments.forms import PaymentForm, SupplierPaymentForm
from apps.payments.models import FinancialAccount, PaymentMethod
from apps.payments.services import record_payment


@pytest.mark.django_db
def test_record_payment_captures_account_and_payment_metadata():
    sale = SaleFactory(agreed_amount=Decimal("15000.00"), currency="USD")
    user = UserFactory(company=sale.company)

    with company_scope(sale.company):
        account = FinancialAccount.objects.create(
            company=sale.company,
            name="Kabul USD Cashbox",
            account_type="CASH",
            currency="USD",
            active=True,
        )
        entry = record_payment(
            sale,
            Decimal("500.00"),
            "USD",
            user=user,
            account=account,
            payment_method=PaymentMethod.BANK_TRANSFER,
            transaction_date=date(2026, 8, 30),
            reference="REF-2026-001",
            receipt_number="RCT-2026-001",
            description="Initial payment",
        )

    assert entry.account == account
    assert entry.payment_method == PaymentMethod.BANK_TRANSFER
    assert entry.reference == "REF-2026-001"
    assert entry.receipt_number == "RCT-2026-001"
    assert entry.transaction_date == date(2026, 8, 30)


@pytest.mark.django_db
def test_finance_forms_include_required_ledger_metadata_and_help_text():
    payment_form = PaymentForm()
    for field_name in [
        "sale",
        "amount",
        "currency",
        "account",
        "payment_method",
        "transaction_date",
        "reference",
        "receipt_number",
        "description",
    ]:
        assert field_name in payment_form.fields
        assert payment_form.fields[field_name].help_text, f"Missing help text for {field_name}"

    supplier_form = SupplierPaymentForm()
    for field_name in [
        "supplier",
        "amount",
        "currency",
        "account",
        "payment_method",
        "transaction_date",
        "reference",
        "receipt_number",
        "description",
    ]:
        assert field_name in supplier_form.fields
        assert supplier_form.fields[field_name].help_text, f"Missing help text for {field_name}"

    expense_form = ExpenseForm()
    for field_name in [
        "transaction_date",
        "category",
        "amount",
        "currency",
        "account",
        "branch",
        "vendor",
        "reference",
        "description",
    ]:
        assert field_name in expense_form.fields
        assert expense_form.fields[field_name].help_text, f"Missing help text for {field_name}"


@pytest.mark.django_db
def test_financial_account_uses_company_scope_and_currency():
    sale = SaleFactory(agreed_amount=Decimal("12000.00"), currency="AFN")

    with company_scope(sale.company):
        account = FinancialAccount.objects.create(
            company=sale.company,
            name="Kabul AFN Bank",
            account_type="BANK",
            currency="AFN",
            active=True,
        )

    assert account.company == sale.company
    assert account.currency == "AFN"
    assert account.account_type == "BANK"


@pytest.mark.django_db
def test_receipt_numbers_are_generated_sequentially_per_company():
    sale = SaleFactory(agreed_amount=Decimal("12000.00"), currency="AFN")
    with company_scope(sale.company):
        first = record_payment(sale, Decimal("100.00"), "AFN")
        second = record_payment(sale, Decimal("100.00"), "AFN")
    assert first.receipt_number.startswith("RCT-")
    assert first.receipt_number != second.receipt_number
    assert int(second.receipt_number.rsplit("-", 1)[1]) == int(
        first.receipt_number.rsplit("-", 1)[1]
    ) + 1
