from django.shortcuts import render

from apps.core.decorators import require_permission
from apps.sales.models import Sale, SaleStatus

from .services import ledger_balance, money_in, money_out, sale_payment_summary


def _receivable_rows():
    completed_sales = Sale.objects.filter(status=SaleStatus.COMPLETED).select_related(
        "customer", "vehicle", "finance_agreement"
    )
    rows = []
    for sale in completed_sales:
        payment = sale_payment_summary(sale)
        if payment["outstanding"] > 0:
            rows.append({"sale": sale, "payment": payment})
    return rows


@require_permission("payments.view")
def summary(request):
    """Financial overview: everything here is computed from ledger rows (§6)."""
    outstanding = _receivable_rows()
    return render(
        request,
        "accounting/summary.html",
        {
            "balance": ledger_balance(),
            "money_in": money_in(),
            "money_out": money_out(),
            "outstanding": outstanding,
        },
    )


@require_permission("payments.view")
def receivables(request):
    """Every completed sale with any positive customer balance."""
    rows = _receivable_rows()
    totals = {}
    for row in rows:
        payment = row["payment"]
        currency = payment["currency"]
        totals[currency] = totals.get(currency, 0) + payment["outstanding"]
    return render(
        request,
        "accounting/receivables.html",
        {
            "rows": rows,
            "totals": totals,
            "can_add_financing": request.user.has_permission("financing.add"),
        },
    )
