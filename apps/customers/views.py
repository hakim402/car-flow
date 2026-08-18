from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.decorators import require_permission

from .forms import CustomerForm
from .models import Customer


@require_permission("customers.view")
def customer_list(request):
    search = request.GET.get("q", "").strip()
    queryset = Customer.objects.all()  # TenantManager filters by company.
    if search:
        queryset = queryset.filter(full_name__icontains=search) | queryset.filter(
            phone__icontains=search
        )
    return render(request, "customers/list.html", {"customers": queryset, "q": search})


@require_permission("customers.add")
def customer_create(request):
    if request.user.company is None:
        raise PermissionDenied
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        customer = form.save(commit=False)
        customer.company = request.user.company
        customer.created_by = request.user
        customer.save()
        messages.success(request, _("Customer created."))
        return redirect(customer)
    return render(request, "customers/form.html", {"form": form, "title": _("Add customer")})


@require_permission("customers.view")
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    return render(
        request,
        "customers/detail.html",
        {
            "customer": customer,
            "sales": customer.sales.select_related("vehicle"),
            "leads": customer.leads.all(),
        },
    )


@require_permission("customers.change")
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Customer updated."))
        return redirect(customer)
    return render(
        request,
        "customers/form.html",
        {"form": form, "title": _("Edit customer"), "customer": customer},
    )
