"""PostgreSQL-backed concurrency gates (README §26, §28).

Racing write paths must serialize through row locks and database
uniqueness. These tests need a real PostgreSQL transaction engine —
`select_for_update` and unique-constraint races are meaningless on SQLite's
single-writer model, so the module skips itself there. Run inside Docker:

    docker compose run --rm web pytest --ds=config.settings.test_postgres \\
        apps/core/tests/test_integrity_concurrency.py
"""
import datetime
import threading
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.branches.models import Branch
from apps.core.tenancy import company_scope
from apps.core.testing import OrganizationFactory, SaleFactory, SupplierFactory, VehicleFactory
from apps.payments.models import LedgerEntry
from apps.payments.services import record_payment, reverse_entry
from apps.purchases.models import PurchaseOrder, PurchaseOrderLine, PurchaseStatus
from apps.purchases.receiving import receive_order
from apps.sales.models import Invoice
from apps.sales.services import issue_invoice

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL concurrency semantics required (README §26)",
    ),
]


def _run_concurrently(fns):
    """Run each callable in its own thread with a fresh DB connection, all
    released from the same barrier. Returns (results, errors)."""
    barrier = threading.Barrier(len(fns))
    results = [None] * len(fns)
    errors = [None] * len(fns)

    def worker(index):
        try:
            connection.close()  # fresh connection per thread
            results[index] = fns[index](barrier)
        except Exception as exc:  # noqa: BLE001 - collected for the asserts
            errors[index] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(fns))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, errors


def test_two_racing_requests_issue_one_invoice():
    sale = SaleFactory(agreed_amount=Decimal("15000.00"))
    company = sale.company

    def call(barrier):
        with company_scope(company), transaction.atomic():
            barrier.wait()
            return issue_invoice(sale).pk

    results, errors = _run_concurrently([call, call])
    assert errors == [None, None]
    assert results[0] == results[1]  # both callers got the same invoice
    assert Invoice.all_objects.filter(sale=sale).count() == 1


def test_two_racing_reversals_produce_one_reversal():
    sale = SaleFactory(agreed_amount=Decimal("15000.00"))
    company = sale.company
    with company_scope(company):
        entry = record_payment(sale, Decimal("5000.00"), "USD")

    def call(barrier):
        with company_scope(company), transaction.atomic():
            barrier.wait()
            return reverse_entry(entry)

    results, errors = _run_concurrently([call, call])
    successes = [r for r, e in zip(results, errors) if e is None]
    failures = [e for e in errors if e is not None]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ValidationError)
    assert LedgerEntry.all_objects.filter(reversal_of=entry).count() == 1


def test_two_racing_receivers_apply_stock_once():
    company = OrganizationFactory()
    supplier = SupplierFactory(company=company)
    order = PurchaseOrder.all_objects.create(
        company=company,
        supplier=supplier,
        order_date=datetime.date.today(),
        status=PurchaseStatus.ORDERED,
    )
    # receive_order only places vehicles into branch stock when a branch is
    # known (order.branch or vehicle.branch) — mirror the import-workflow
    # fixture so the stock assertion below is meaningful.
    order.branch = Branch.objects.create(company=company, name="HQ")
    order.save(update_fields=["branch"])
    vehicle = VehicleFactory(company=company)
    PurchaseOrderLine.objects.create(
        order=order,
        vehicle=vehicle,
        description="Toyota Corolla",
        amount=Decimal("15000.00"),
        currency="USD",
    )

    def call(barrier):
        with company_scope(company):
            barrier.wait()
            return receive_order(order)

    results, errors = _run_concurrently([call, call])
    assert errors == [None, None]
    assert sorted(results) == [0, 1]  # one winner, the loser sees RECEIVED

    from apps.inventory.models import VehicleStock
    from apps.purchases.models import CostType, VehicleCostLine

    assert (
        VehicleCostLine.all_objects.filter(
            vehicle=vehicle, cost_type=CostType.PURCHASE
        ).count()
        == 1
    )
    assert VehicleStock.all_objects.filter(vehicle=vehicle).count() == 1
