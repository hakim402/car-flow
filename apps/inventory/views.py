from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission

from .models import StockStatus, VehicleStock


@require_permission("inventory.view")
def stock_list(request):
    queryset = VehicleStock.objects.all()  # TenantManager filters by company.
    if request.user.branch_id:
        queryset = queryset.filter(branch_id=request.user.branch_id)
    status = request.GET.get("status", "")
    if status in StockStatus.values:
        queryset = queryset.filter(status=status)
    return render(
        request,
        "inventory/list.html",
        {
            "stock_items": queryset.select_related("vehicle", "branch"),
            "statuses": StockStatus.choices,
            "status": status,
        },
    )


@require_permission("inventory.change")
@require_POST
def stock_update_status(request, pk):
    item = get_object_or_404(VehicleStock, pk=pk)
    new_status = request.POST.get("status", "")
    if new_status in StockStatus.values:
        item.status = new_status
        item.save(update_fields=["status"])
    return redirect("inventory:list")
