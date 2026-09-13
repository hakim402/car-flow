"""Supplier payments through the ledger (agent.md §6).

Paying a supplier for an import invoice is money OUT: one immutable
SUPPLIER_PAYMENT row pointing at the supplier, totals computed — never
stored — and corrections only via reversal rows."""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.accounting.services import supplier_payments
from apps.core.tenancy import company_scope
from apps.core.testing import SupplierFactory, UserFactory
from apps.payments.models import EntryType, FinancialAccount, LedgerEntry, PaymentMethod
from apps.payments.services import record_supplier_payment, reverse_entry
from apps.purchases.models import PurchaseOrder, PurchaseOrderLine

ZERO = Decimal("0.00")


@pytest.fixture
def finance_user(db):
    """Company user holding the payments/supplier permissions the views check."""
    user = UserFactory()
    permissions = [
        Permission.objects.get_or_create(codename=codename)[0]
        for codename in ("payments.view", "payments.add", "suppliers.view")
    ]
    role, _ = Role.objects.get_or_create(
        key="supplier_payment_test", defaults={"name": "Supplier payment test"}
    )
    role.permissions.set(permissions)
    user.roles.add(role)
    return user


@pytest.fixture
def supplier(finance_user):
    return SupplierFactory(company=finance_user.company, name="Gulf Auto Trading")


def _payment_context(supplier, currency="USD"):
    account = FinancialAccount.objects.create(
        company=supplier.company,
        name=f"Supplier {currency} cashbox",
        currency=currency,
        active=True,
    )
    order = PurchaseOrder.objects.create(
        company=supplier.company,
        supplier=supplier,
        reference=f"PO-{currency}-001",
        order_date=date.today(),
    )
    PurchaseOrderLine.objects.create(
        order=order,
        description="Vehicle purchase",
        amount=Decimal("10000.00"),
        currency=currency,
    )
    return account, order


@pytest.mark.django_db
def test_record_supplier_payment_writes_ledger_row(finance_user, supplier):
    with company_scope(finance_user.company):
        account, order = _payment_context(supplier)
        entry = record_supplier_payment(
            supplier, Decimal("5000.00"), "USD", user=finance_user,
            description="PO IMP-1 deposit", account=account, purchase_order=order,
        )

    assert entry.type == EntryType.SUPPLIER_PAYMENT
    assert entry.direction == "out"
    assert entry.company == finance_user.company
    assert entry.related_object == supplier


@pytest.mark.django_db
def test_supplier_payments_totals_net_reversals(supplier):
    with company_scope(supplier.company):
        usd_account, usd_order = _payment_context(supplier)
        afn_account, afn_order = _payment_context(supplier, "AFN")
        first = record_supplier_payment(
            supplier, Decimal("5000.00"), "USD",
            account=usd_account, purchase_order=usd_order,
        )
        record_supplier_payment(
            supplier, Decimal("1200.00"), "AFN",
            account=afn_account, purchase_order=afn_order,
        )

        totals = supplier_payments(supplier)
        assert totals["USD"] == Decimal("5000.00")
        assert totals["AFN"] == Decimal("1200.00")

        # Correcting a payment appends a mirror row; the total shrinks, the
        # original row is never touched.
        reverse_entry(first, description="Supplier payment correction")
        totals = supplier_payments(supplier)
    assert totals["USD"] == ZERO
    assert LedgerEntry.all_objects.filter(pk=first.pk).exists()


@pytest.mark.django_db
def test_supplier_payment_cannot_exceed_purchase_order_balance(supplier):
    with company_scope(supplier.company):
        account, order = _payment_context(supplier)
        with pytest.raises(ValidationError, match="outstanding balance"):
            record_supplier_payment(
                supplier,
                Decimal("10000.01"),
                "USD",
                account=account,
                purchase_order=order,
            )


@pytest.mark.django_db
def test_pay_supplier_view_records_and_redirects(client, finance_user, supplier):
    with company_scope(finance_user.company):
        account, order = _payment_context(supplier)
    client.force_login(finance_user)

    response = client.post(
        reverse("payments:supplier_payment"),
        {
            "supplier": supplier.pk,
            "purchase_order": order.pk,
            "account": account.pk,
            "amount": "3500.00",
            "currency": "USD",
            "payment_method": PaymentMethod.CASH,
            "description": "Invoice 2026-114",
        },
    )

    assert response.status_code == 302
    entry = LedgerEntry.all_objects.get(description="Invoice 2026-114")
    assert response.headers["Location"] == reverse("payments:detail", args=[entry.pk])
    assert entry.type == EntryType.SUPPLIER_PAYMENT
    assert entry.amount == Decimal("3500.00")
    assert entry.created_by == finance_user


@pytest.mark.django_db
def test_supplier_detail_shows_payment_history_and_totals(client, finance_user, supplier):
    with company_scope(finance_user.company):
        account, order = _payment_context(supplier)
        record_supplier_payment(
            supplier,
            Decimal("5000.00"),
            "USD",
            description="Deposit",
            account=account,
            purchase_order=order,
        )
    client.force_login(finance_user)

    response = client.get(supplier.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert "Deposit" in content
    assert "5000.00 USD" in content.replace("\xa0", " ") or "5000.00" in content
    assert "Record payment" in content
    assert reverse("payments:supplier_payment") in content


@pytest.mark.django_db
def test_pay_foreign_company_supplier_404s(client, finance_user):
    foreign_supplier = SupplierFactory()  # its own (different) company
    client.force_login(finance_user)

    response = client.get(
        reverse("payments:supplier_payment") + f"?supplier={foreign_supplier.pk}"
    )

    assert response.status_code == 404
