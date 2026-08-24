"""Service-layer integrity guards (README §25.2, §26, §28).

Write paths validate cross-tenant references and enforce reversal / invoice /
receiving rules BEFORE the database has to reject anything, so callers get
business errors (`ValidationError`) instead of constraint crashes.
"""
import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.tenancy import company_scope
from apps.core.testing import (
    CustomerFactory,
    OrganizationFactory,
    SaleFactory,
    SupplierFactory,
    VehicleFactory,
)
from apps.payments.models import LedgerEntry
from apps.payments.services import record_payment, reverse_entry
from apps.purchases.models import PurchaseOrder, PurchaseStatus
from apps.purchases.receiving import receive_order
from apps.sales.models import Invoice, Sale, SaleStatus
from apps.sales.services import complete_sale, issue_invoice


@pytest.fixture
def sale(db):
    return SaleFactory(agreed_amount=Decimal("15000.00"), currency="USD")


# --------------------------------------------------------------------------
# Reversal rules (README §16): a reversal cannot be reversed, and an entry
# can be reversed at most once.


@pytest.mark.django_db
def test_reverse_entry_rejects_reversing_a_reversal(sale):
    with company_scope(sale.company):
        entry = record_payment(sale, Decimal("100.00"), "USD")
        reversal = reverse_entry(entry)
        with pytest.raises(ValidationError):
            reverse_entry(reversal)


@pytest.mark.django_db
def test_reverse_entry_rejects_double_reversal(sale):
    with company_scope(sale.company):
        entry = record_payment(sale, Decimal("100.00"), "USD")
        reverse_entry(entry)
        with pytest.raises(ValidationError):
            reverse_entry(entry)
    assert LedgerEntry.all_objects.filter(reversal_of=entry).count() == 1


# --------------------------------------------------------------------------
# Invoice: idempotent issuance, one invoice per sale (README §28).


@pytest.mark.django_db
def test_issue_invoice_is_idempotent(sale):
    with company_scope(sale.company):
        first = issue_invoice(sale)
        second = issue_invoice(sale)
    assert first.pk == second.pk
    assert Invoice.all_objects.filter(sale=sale).count() == 1


# --------------------------------------------------------------------------
# Cross-tenant references must be rejected by the write paths (§25.2).


@pytest.mark.django_db
def test_complete_sale_rejects_cross_company_customer():
    foreign_customer = CustomerFactory()  # its own company
    sale = SaleFactory()
    sale.customer = foreign_customer

    with company_scope(sale.company):
        with pytest.raises(ValidationError):
            complete_sale(sale)

    untouched = Sale.all_objects.get(pk=sale.pk)
    assert untouched.status == SaleStatus.DRAFT


@pytest.mark.django_db
def test_record_payment_rejects_cross_company_customer():
    foreign_customer = CustomerFactory()  # its own company
    sale = SaleFactory()
    sale.customer = foreign_customer

    with company_scope(sale.company):
        with pytest.raises(ValidationError):
            record_payment(sale, Decimal("100.00"), "USD")


@pytest.mark.django_db
def test_receive_order_rejects_cross_company_supplier():
    company = OrganizationFactory()
    foreign_supplier = SupplierFactory()  # its own company
    order = PurchaseOrder.all_objects.create(
        company=company,
        supplier=foreign_supplier,
        order_date=datetime.date.today(),
        status=PurchaseStatus.ORDERED,
    )

    with company_scope(company):
        with pytest.raises(ValidationError):
            receive_order(order)

    untouched = PurchaseOrder.all_objects.get(pk=order.pk)
    assert untouched.status == PurchaseStatus.ORDERED


# --------------------------------------------------------------------------
# Receiving guards (README §6.2, §26): CANCELLED orders are never receivable.


@pytest.mark.django_db
def test_receive_order_refuses_cancelled_order():
    company = OrganizationFactory()
    supplier = SupplierFactory(company=company)
    order = PurchaseOrder.all_objects.create(
        company=company,
        supplier=supplier,
        order_date=datetime.date.today(),
        status=PurchaseStatus.CANCELLED,
    )

    with company_scope(company):
        assert receive_order(order) == 0
    assert PurchaseOrder.all_objects.get(pk=order.pk).status == PurchaseStatus.CANCELLED


@pytest.mark.django_db
def test_receive_order_places_stock_and_is_idempotent():
    company = OrganizationFactory()
    supplier = SupplierFactory(company=company)
    vehicle = VehicleFactory(company=company)
    order = PurchaseOrder.all_objects.create(
        company=company,
        supplier=supplier,
        order_date=datetime.date.today(),
        status=PurchaseStatus.ORDERED,
    )
    from apps.purchases.models import PurchaseOrderLine

    PurchaseOrderLine.objects.create(
        order=order,
        vehicle=vehicle,
        description="Toyota Corolla",
        amount=Decimal("15000.00"),
        currency="USD",
    )

    with company_scope(company):
        assert receive_order(order) == 1
        assert receive_order(order) == 0  # RECEIVED orders stop

    from apps.purchases.models import CostType, VehicleCostLine

    assert (
        VehicleCostLine.all_objects.filter(
            vehicle=vehicle, cost_type=CostType.PURCHASE
        ).count()
        == 1
    )
