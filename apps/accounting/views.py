from django.shortcuts import render

from apps.core.decorators import require_permission
from apps.sales.models import Sale, SaleStatus

from .services import ledger_balance, money_in, money_out, sale_outstanding


@require_permission("payments.view")
def summary(request):
    """Financial overview: everything here is computed from ledger rows (§6)."""
    completed_sales = Sale.objects.filter(status=SaleStatus.COMPLETED).select_related("customer")
    outstanding = [
        {"sale": sale, "amounts": sale_outstanding(sale)}
        for sale in completed_sales
    ]
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
