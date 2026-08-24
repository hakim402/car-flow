"""Database-level integrity constraints (README §28).

Forms are not enough: these tests prove the DATABASE itself rejects
violations even when callers bypass validation entirely (shell scripts,
imports, future code). They run on the SQLite suite; the PostgreSQL-backed
race conditions have their own module (`test_integrity_concurrency.py`).
"""
import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.testing import (
    CustomerFactory,
    OrganizationFactory,
    SaleFactory,
    SupplierFactory,
    VehicleFactory,
)
from apps.core.validation import validate_same_company
from apps.documents.models import Document, DocumentType
from apps.payments.models import EntryType, LedgerEntry
from apps.purchases.models import CostType, PurchaseOrderLine, VehicleCostLine
from apps.sales.models import Invoice, Reservation, Sale, SaleStatus
from apps.vehicles.models import Vehicle

# --------------------------------------------------------------------------
# Same-company validation (README §25.2) — the reusable helper itself.


@pytest.mark.django_db
def test_validate_same_company_rejects_cross_tenant():
    company_a, company_b = OrganizationFactory(), OrganizationFactory()
    customer_a = CustomerFactory(company=company_a)

    with pytest.raises(ValidationError):
        validate_same_company(company_b, {"customer": customer_a})

    # Same company, None values and non-tenant objects all pass.
    validate_same_company(company_a, {"customer": customer_a, "optional": None})
    validate_same_company(None, {"customer": customer_a})  # no company: no rule


@pytest.mark.django_db
def test_mixin_clean_blocks_cross_company_row():
    """`full_clean()` (model forms, services that call it) refuses to save a
    row whose relation belongs to another company."""
    company_a, company_b = OrganizationFactory(), OrganizationFactory()
    customer_a = CustomerFactory(company=company_a)
    vehicle_b = VehicleFactory(company=company_b)

    sale = Sale(
        company=company_b,
        customer=customer_a,  # foreign!
        vehicle=vehicle_b,
        agreed_amount=Decimal("15000.00"),
        currency="USD",
        sale_date=datetime.date.today(),
    )
    with pytest.raises(ValidationError):
        sale.full_clean()

    sale.customer = CustomerFactory(company=company_b)
    sale.full_clean()  # now consistent


# --------------------------------------------------------------------------
# Document: exactly one target (README §28).


@pytest.mark.django_db
def test_document_requires_exactly_one_target():
    company = OrganizationFactory()
    vehicle = VehicleFactory(company=company)
    customer = CustomerFactory(company=company)
    supplier = SupplierFactory(company=company)

    with pytest.raises(IntegrityError):  # zero targets
        with transaction.atomic():
            Document.all_objects.create(company=company, doc_type=DocumentType.OTHER, title="none")

    with pytest.raises(IntegrityError):  # two targets
        with transaction.atomic():
            Document.all_objects.create(
                company=company,
                doc_type=DocumentType.OTHER,
                title="two",
                vehicle=vehicle,
                customer=customer,
            )

    Document.all_objects.create(  # exactly one: accepted
        company=company, doc_type=DocumentType.OTHER, title="ok", vehicle=vehicle
    )
    Document.all_objects.create(  # exactly one, other leg: accepted
        company=company, doc_type=DocumentType.OTHER, title="ok", supplier=supplier
    )


# --------------------------------------------------------------------------
# Invoice: one per sale, positive amounts (README §28).


@pytest.mark.django_db
def test_invoice_unique_per_sale_and_positive_amount():
    sale = SaleFactory(agreed_amount=Decimal("15000.00"))
    other_sale = SaleFactory(company=sale.company, agreed_amount=Decimal("9000.00"))

    Invoice.all_objects.create(
        company=sale.company,
        sale=sale,
        number="INV-000001",
        issued_on=datetime.date.today(),
        amount=Decimal("15000.00"),
        currency="USD",
    )
    with pytest.raises(IntegrityError):  # second invoice for the same sale
        with transaction.atomic():
            Invoice.all_objects.create(
                company=sale.company,
                sale=sale,
                number="INV-000002",
                issued_on=datetime.date.today(),
                amount=Decimal("1.00"),
                currency="USD",
            )
    with pytest.raises(IntegrityError):  # non-positive amount
        with transaction.atomic():
            Invoice.all_objects.create(
                company=sale.company,
                sale=other_sale,
                number="INV-000003",
                issued_on=datetime.date.today(),
                amount=Decimal("0.00"),
                currency="USD",
            )


# --------------------------------------------------------------------------
# Reservation: at most one ACTIVE per vehicle (partial uniqueness).


@pytest.mark.django_db
def test_one_active_reservation_per_vehicle():
    company = OrganizationFactory()
    customer = CustomerFactory(company=company)
    vehicle = VehicleFactory(company=company)

    Reservation.all_objects.create(
        company=company,
        customer=customer,
        vehicle=vehicle,
        deposit_amount=Decimal("500.00"),
        currency="USD",
        status="active",
    )
    with pytest.raises(IntegrityError):  # second ACTIVE for the same vehicle
        with transaction.atomic():
            Reservation.all_objects.create(
                company=company,
                customer=customer,
                vehicle=vehicle,
                deposit_amount=Decimal("600.00"),
                currency="USD",
                status="active",
            )
    # Non-ACTIVE rows do not conflict with the ACTIVE one.
    Reservation.all_objects.create(
        company=company,
        customer=customer,
        vehicle=vehicle,
        deposit_amount=Decimal("600.00"),
        currency="USD",
        status="cancelled",
    )


# --------------------------------------------------------------------------
# LedgerEntry: one reversal per original, positive amounts (README §16, §28).


@pytest.mark.django_db
def test_ledger_entry_reversal_unique_and_positive():
    company = OrganizationFactory()
    original = LedgerEntry.all_objects.create(
        company=company,
        type=EntryType.CUSTOMER_PAYMENT,
        amount=Decimal("100.00"),
        currency="USD",
    )
    LedgerEntry.all_objects.create(
        company=company,
        type=EntryType.CUSTOMER_PAYMENT,
        amount=Decimal("100.00"),
        currency="USD",
        reversal_of=original,
    )
    with pytest.raises(IntegrityError):  # second reversal of the same original
        with transaction.atomic():
            LedgerEntry.all_objects.create(
                company=company,
                type=EntryType.CUSTOMER_PAYMENT,
                amount=Decimal("100.00"),
                currency="USD",
                reversal_of=original,
            )
    with pytest.raises(IntegrityError):  # non-positive amount
        with transaction.atomic():
            LedgerEntry.all_objects.create(
                company=company,
                type=EntryType.EXPENSE,
                amount=Decimal("-1.00"),
                currency="USD",
            )


# --------------------------------------------------------------------------
# Purchase money rows: positive amounts (README §28).


@pytest.mark.django_db
def test_purchase_money_rows_are_positive():
    company = OrganizationFactory()
    supplier = SupplierFactory(company=company)
    vehicle = VehicleFactory(company=company)
    from apps.purchases.models import PurchaseOrder

    order = PurchaseOrder.all_objects.create(
        company=company,
        supplier=supplier,
        order_date=datetime.date.today(),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PurchaseOrderLine.objects.create(
                order=order, description="bad", amount=Decimal("0.00"), currency="USD"
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            VehicleCostLine.all_objects.create(
                company=company,
                vehicle=vehicle,
                cost_type=CostType.PURCHASE,
                amount=Decimal("-10.00"),
                currency="USD",
            )
