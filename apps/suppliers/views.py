from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.accounting.services import supplier_payments
from apps.core.decorators import require_permission
from apps.documents.models import Document, DocumentType
from apps.payments.models import EntryType, LedgerEntry

from .forms import SupplierForm
from .models import Supplier


@require_permission("suppliers.view")
def supplier_list(request):
    search = request.GET.get("q", "").strip()
    queryset = Supplier.objects.all()  # TenantManager filters by company.
    queryset = queryset.prefetch_related(
        Prefetch(
            "documents",
            queryset=Document.objects.filter(doc_type=DocumentType.SUPPLIER_LOGO).order_by(
                "-created_at", "-pk"
            ),
            to_attr="logo_list",
        )
    )
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


@require_permission("suppliers.view")
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    orders = supplier.purchase_orders.select_related("branch")
    payments = LedgerEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(Supplier),
        object_id=supplier.pk,
        type=EntryType.SUPPLIER_PAYMENT,
    )
    attachments = supplier.documents.all().select_related("uploaded_by")
    return render(
        request,
        "suppliers/detail.html",
        {
            "supplier": supplier,
            "orders": orders,
            "order_count": orders.count(),
            "payments": payments,
            "total_paid": supplier_payments(supplier),
            "logo": supplier.logo,
            "documents": [a for a in attachments if not a.is_photo],
            "can_edit": request.user.has_permission("suppliers.change"),
            "can_record_payments": request.user.has_permission("payments.add"),
            "can_upload_documents": request.user.has_permission("documents.add"),
        },
    )


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
