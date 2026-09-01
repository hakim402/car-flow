"""Computed financial state (agent.md §6): balances and outstanding amounts
are aggregates over ledger rows — never stored columns that can drift."""
from decimal import Decimal

from apps.core.tenancy import get_current_company
from apps.payments.models import LedgerEntry


def _net_totals(entries) -> dict[str, Decimal]:
    """Net amount per currency; a reversal row subtracts its original.

    A reversal row has the same type as the original, so its direction
    alone cannot tell us which total it cancels: it must be counted
    against the ORIGINAL row's direction (an expense reversal reduces
    money_out, a payment reversal reduces money_in)."""
    entries = list(entries)  # may arrive as a generator; we walk it twice
    by_pk = {entry.pk: entry for entry in entries}
    totals: dict[str, Decimal] = {}
    for entry in entries:
        signed = entry.signed_amount
        if entry.reversal_of_id is not None:
            original = by_pk.get(entry.reversal_of_id)
            direction = original.direction if original else entry.direction
            signed = entry.amount if direction == "in" else -entry.amount
            signed = -signed
        totals[entry.currency] = totals.get(entry.currency, Decimal("0")) + signed
    return totals


def _ledger_queryset(company=None):
    """Return tenant-scoped or platform-wide entries depending on context.

    For Super Admin dashboard views, no company is attached to the user, so the
    system intentionally uses the explicit `all_objects` escape hatch instead of
    failing closed. Regular company users still hit the tenant manager and must
    have an active company context.
    """
    if company is not None:
        return LedgerEntry.objects.filter(company=company)
    current_company = get_current_company()
    if current_company is not None:
        return LedgerEntry.objects.filter(company=current_company)
    return LedgerEntry.all_objects.all()


def ledger_balance(company=None) -> dict[str, Decimal]:
    """Cash position per currency for the current tenant (in minus out)."""
    return _net_totals(_ledger_queryset(company))


def money_in(company=None) -> dict[str, Decimal]:
    """Gross received per currency, net of payment reversals (positive)."""
    return {
        currency: total
        for currency, total in _net_totals(
            e for e in _ledger_queryset(company) if e.direction == "in"
        ).items()
    }


def money_out(company=None) -> dict[str, Decimal]:
    """Gross paid out per currency, net of reversals (positive magnitude)."""
    return {
        currency: -total
        for currency, total in _net_totals(
            e for e in _ledger_queryset(company) if e.direction == "out"
        ).items()
    }


def sale_payments(sale) -> dict[str, Decimal]:
    """Customer payments recorded against a sale, net of reversals."""
    entries = LedgerEntry.objects.filter(
        object_id=sale.pk,
        content_type_id=_sale_content_type_id(),
    )
    return _net_totals(entries)


def sale_outstanding(sale) -> dict[str, Decimal]:
    """What the customer still owes on a sale, per currency (§9: no
    conversion here — a sale agreed in USD stays USD)."""
    paid = sale_payments(sale)
    outstanding = {sale.currency: sale.agreed_amount}
    for currency, amount in paid.items():
        outstanding[currency] = outstanding.get(currency, Decimal("0")) - amount
    return outstanding


def supplier_payments(supplier) -> dict[str, Decimal]:
    """Money paid out to a supplier, net of reversals, per currency
    (positive magnitude — mirrors `money_out`)."""
    entries = LedgerEntry.objects.filter(
        object_id=supplier.pk,
        content_type_id=_supplier_content_type_id(),
    )
    return {
        currency: -total
        for currency, total in _net_totals(entries).items()
    }


def _supplier_content_type_id():
    from django.contrib.contenttypes.models import ContentType

    from apps.suppliers.models import Supplier

    return ContentType.objects.get_for_model(Supplier).pk


def _sale_content_type_id():
    from django.contrib.contenttypes.models import ContentType

    from apps.sales.models import Sale

    return ContentType.objects.get_for_model(Sale).pk
