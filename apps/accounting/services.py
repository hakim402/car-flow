"""Computed financial state (agent.md §6): balances and outstanding amounts
are aggregates over ledger rows — never stored columns that can drift."""
from decimal import Decimal

from django.db.models import Q

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


def sale_payments(sale, as_of=None) -> dict[str, Decimal]:
    """Customer payments applied to a sale, net of reversals.

    A deposit paid while a reservation is active remains one immutable ledger
    event.  When that reservation becomes a sale, the same event is carried
    into the sale balance instead of being copied as a second payment.
    """
    relation = Q(sale=sale)
    if sale.reservation_id:
        relation |= Q(reservation_id=sale.reservation_id)
    entries = LedgerEntry.objects.filter(relation).distinct()
    if as_of:
        entries = entries.filter(transaction_date__lte=as_of)
    return _net_totals(entries)


def reservation_payments(reservation, as_of=None) -> dict[str, Decimal]:
    """Actual customer money received against a reservation."""
    entries = LedgerEntry.objects.filter(reservation=reservation)
    if as_of:
        entries = entries.filter(transaction_date__lte=as_of)
    return _net_totals(entries)


def reservation_payment_summary(reservation) -> dict[str, Decimal | str]:
    """Compare the requested deposit with immutable money received."""
    paid = reservation_payments(reservation).get(reservation.currency, Decimal("0"))
    raw_outstanding = reservation.deposit_amount - paid
    outstanding = max(raw_outstanding, Decimal("0"))
    credit = max(-raw_outstanding, Decimal("0"))
    if outstanding <= 0:
        status = "paid"
    elif paid > 0:
        status = "partial"
    else:
        status = "unpaid"
    return {
        "requested": reservation.deposit_amount,
        "paid": paid,
        "outstanding": outstanding,
        "credit": credit,
        "currency": reservation.currency,
        "status": status,
    }


def sale_payment_summaries(sales, as_of=None) -> dict[int, dict[str, Decimal | str]]:
    """Bulk version of :func:`sale_payment_summary` for list/report views."""
    sales = list(sales)
    if not sales:
        return {}
    sale_ids = [sale.pk for sale in sales]
    reservation_ids = [sale.reservation_id for sale in sales if sale.reservation_id]
    relation = Q(sale_id__in=sale_ids)
    if reservation_ids:
        relation |= Q(reservation_id__in=reservation_ids)
    entries_query = LedgerEntry.objects.filter(relation)
    if as_of:
        entries_query = entries_query.filter(transaction_date__lte=as_of)
    entries = list(
        entries_query
        .select_related("reversal_of")
        .distinct()
    )
    by_sale, by_reservation = {}, {}
    for entry in entries:
        by_sale.setdefault(entry.sale_id, []).append(entry)
        by_reservation.setdefault(entry.reservation_id, []).append(entry)
    summaries = {}
    for sale in sales:
        related = {entry.pk: entry for entry in by_sale.get(sale.pk, [])}
        if sale.reservation_id:
            related.update({entry.pk: entry for entry in by_reservation.get(sale.reservation_id, [])})
        paid = _net_totals(related.values()).get(sale.currency, Decimal("0"))
        summaries[sale.pk] = _payment_summary(sale.agreed_amount, paid, sale.currency)
    return summaries


def reservation_payment_summaries(reservations) -> dict[int, dict[str, Decimal | str]]:
    """Bulk requested-versus-received summaries for reservation lists."""
    reservations = list(reservations)
    if not reservations:
        return {}
    entries = list(
        LedgerEntry.objects.filter(reservation_id__in=[item.pk for item in reservations])
        .select_related("reversal_of")
    )
    summaries = {}
    for reservation in reservations:
        related = [entry for entry in entries if entry.reservation_id == reservation.pk]
        paid = _net_totals(related).get(reservation.currency, Decimal("0"))
        summaries[reservation.pk] = _payment_summary(
            reservation.deposit_amount,
            paid,
            reservation.currency,
            amount_key="requested",
        )
    return summaries


def _payment_summary(amount, paid, currency, *, amount_key="agreed"):
    raw_outstanding = amount - paid
    outstanding = max(raw_outstanding, Decimal("0"))
    credit = max(-raw_outstanding, Decimal("0"))
    if outstanding <= 0:
        status = "paid"
    elif paid > 0:
        status = "partial"
    else:
        status = "unpaid"
    return {
        amount_key: amount,
        "paid": paid,
        "outstanding": outstanding,
        "credit": credit,
        "currency": currency,
        "status": status,
    }


def sale_outstanding(sale, as_of=None) -> dict[str, Decimal]:
    """What the customer still owes on a sale, per currency (§9: no
    conversion here — a sale agreed in USD stays USD)."""
    paid = sale_payments(sale, as_of=as_of)
    outstanding = {sale.currency: sale.agreed_amount}
    for currency, amount in paid.items():
        outstanding[currency] = outstanding.get(currency, Decimal("0")) - amount
    return outstanding


def sale_payment_summary(sale, as_of=None) -> dict[str, Decimal | str]:
    """Return the derived payment state for one sale.

    This is the authoritative customer-debt calculation used by sales,
    customer profiles, and receivables.  Even a very small positive balance
    remains outstanding; no mutable ``paid`` or ``balance`` column can drift
    away from the immutable ledger.
    """
    paid = sale_payments(sale, as_of=as_of).get(sale.currency, Decimal("0"))
    return _payment_summary(sale.agreed_amount, paid, sale.currency)


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
