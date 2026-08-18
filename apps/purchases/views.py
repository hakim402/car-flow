from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission

from .forms import PurchaseOrderForm, PurchaseOrderLineForm
from .models import PurchaseOrder, PurchaseStatus
from .receiving import receive_order


@require_permission("purchases.view")
def order_list(request):
    queryset = PurchaseOrder.objects.all()  # TenantManager filters by company.
    return render(
        request,
        "purchases/list.html",
        {"orders": queryset.select_related("supplier", "branch")},
    )


@require_permission("purchases.add")
def order_create(request):
    if request.user.company is None:
        raise PermissionDenied
    form = PurchaseOrderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        order = form.save(commit=False)
        order.company = request.user.company
        order.created_by = request.user
        order.save()
        messages.success(request, _("Purchase order created — add lines next."))
        return redirect(order)
    return render(request, "purchases/form.html", {"form": form, "title": _("New purchase order")})


@require_permission("purchases.view")
def order_detail(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    line_form = PurchaseOrderLineForm()
    return render(
        request,
        "purchases/detail.html",
        {
            "order": order,
            "lines": order.lines.select_related("vehicle"),
            "totals": order.total_by_currency(),
            "line_form": line_form,
            "can_receive": order.status in (PurchaseStatus.DRAFT, PurchaseStatus.ORDERED),
        },
    )


@require_permission("purchases.change")
@require_POST
def order_add_line(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    form = PurchaseOrderLineForm(request.POST)
    if form.is_valid():
        line = form.save(commit=False)
        line.order = order
        line.save()
        messages.success(request, _("Line added."))
    else:
        messages.error(request, _("Could not add line — check the form values."))
    return redirect(order)


@require_permission("purchases.change")
@require_POST
def order_receive(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    count = receive_order(order, user=request.user)
    messages.success(request, _("Order received (%(count)d vehicles into stock).") % {"count": count})
    return redirect(order)
