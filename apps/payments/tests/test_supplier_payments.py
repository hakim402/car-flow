"""Supplier payments through the ledger (agent.md §6).

Paying a supplier for an import invoice is money OUT: one immutable
SUPPLIER_PAYMENT row pointing at the supplier, totals computed — never
stored — and corrections only via reversal rows."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.accounting.services import supplier_payments
from apps.core.testing import SupplierFactory, UserFactory
from apps.payments.models import EntryType, LedgerEntry
from apps.payments.services import record_supplier_payment, reverse_entry

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


@pytest.mark.django_db
def test_record_supplier_payment_writes_ledger_row(finance_user, supplier):
    entry = record_supplier_payment(
        supplier, Decimal("5000.00"), "USD", user=finance_user, description="PO IMP-1 deposit"
    )

    assert entry.type == EntryType.SUPPLIER_PAYMENT
    assert entry.direction == "out"
    assert entry.company == finance_user.company
    assert entry.related_object == supplier


@pytest.mark.django_db
def test_supplier_payments_totals_net_reversals(supplier):
    first = record_supplier_payment(supplier, Decimal("5000.00"), "USD")
    record_supplier_payment(supplier, Decimal("1200.00"), "AFN")

    totals = supplier_payments(supplier)
    assert totals["USD"] == Decimal("5000.00")
    assert totals["AFN"] == Decimal("1200.00")

    # Correcting a payment appends a mirror row; the total shrinks, the
    # original row is never touched.
    reverse_entry(first)
    totals = supplier_payments(supplier)
    assert totals["USD"] == ZERO
    assert LedgerEntry.all_objects.filter(pk=first.pk).exists()


@pytest.mark.django_db
def test_pay_supplier_view_records_and_redirects(client, finance_user, supplier):
    client.force_login(finance_user)

    response = client.post(
        reverse("payments:supplier_payment"),
        {
            "supplier": supplier.pk,
            "amount": "3500.00",
            "currency": "USD",
            "description": "Invoice 2026-114",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == supplier.get_absolute_url()
    entry = LedgerEntry.all_objects.get(description="Invoice 2026-114")
    assert entry.type == EntryType.SUPPLIER_PAYMENT
    assert entry.amount == Decimal("3500.00")
    assert entry.created_by == finance_user


@pytest.mark.django_db
def test_supplier_detail_shows_payment_history_and_totals(client, finance_user, supplier):
    record_supplier_payment(supplier, Decimal("5000.00"), "USD", description="Deposit")
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
