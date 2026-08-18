from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.decorators import require_permission

from .forms import SupplierForm
from .models import Supplier


@require_permission("suppliers.view")
def supplier_list(request):
    search = request.GET.get("q", "").strip()
    queryset = Supplier.objects.all()  # TenantManager filters by company.
    if search:
        queryset = queryset.filter(name__icontains=search)
    return render(request, "suppliers/list.html", {"suppliers": queryset, "q": search})


@require_permission("suppliers.add")
def supplier_create(request):
    if request.user.company is None:
        raise PermissionDenied
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        supplier = form.save(commit=False)
        supplier.company = request.user.company
        supplier.save()
        messages.success(request, _("Supplier created."))
        return redirect("suppliers:list")
    return render(request, "suppliers/form.html", {"form": form, "title": _("Add supplier")})


@require_permission("suppliers.change")
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Supplier updated."))
        return redirect("suppliers:list")
    return render(
        request,
        "suppliers/form.html",
        {"form": form, "title": _("Edit supplier"), "supplier": supplier},
    )
