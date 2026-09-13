from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.accounting.services import supplier_payments
from apps.core.constants import COUNTRIES
from apps.core.decorators import require_permission
from apps.core.pagination import pagination_context
from apps.documents.models import Document, DocumentType
from apps.payments.models import EntryType, LedgerEntry
from apps.purchases.models import PurchaseOrder, PurchaseOrderLine, PurchaseStatus

from .forms import SupplierForm
from .models import Supplier, SupplierKind, SupplierType


@require_permission("suppliers.view")
def supplier_list(request):
    search = request.GET.get("q", "").strip()
    supplier_type = request.GET.get("type", "")
    kind = request.GET.get("kind", "")
    country = request.GET.get("country", "")
    sort = request.GET.get("sort", "name")
    base_queryset = Supplier.objects.all()  # TenantManager filters by company.
    queryset = base_queryset
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(contact_person__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )
    if supplier_type in SupplierType.values:
        queryset = queryset.filter(supplier_type=supplier_type)
    if kind in SupplierKind.values:
        queryset = queryset.filter(kind=kind)
    if country:
        queryset = queryset.filter(country=country)

    ordering = {
        "name": "name",
        "newest": "-created_at",
        "most_orders": "-order_count",
        "recent_purchase": "-last_purchase_date",
    }
    sort = sort if sort in ordering else "name"
    orders = Prefetch(
        "purchase_orders",
        queryset=PurchaseOrder.objects.prefetch_related("lines").order_by("-order_date", "-pk"),
        to_attr="purchase_order_list",
    )
    queryset = queryset.annotate(
        order_count=Count("purchase_orders", distinct=True),
        vehicle_count=Count("purchase_orders__lines__vehicle", distinct=True),
        active_order_count=Count(
            "purchase_orders",
            filter=~Q(
                purchase_orders__status__in=[PurchaseStatus.RECEIVED, PurchaseStatus.CANCELLED]
            ),
            distinct=True,
        ),
        last_purchase_date=Max("purchase_orders__order_date"),
    ).prefetch_related(
        Prefetch(
            "documents",
            queryset=Document.objects.filter(
                doc_type__in=(DocumentType.SUPPLIER_LOGO, DocumentType.SUPPLIER_PHOTO)
            ).order_by("-created_at", "-pk"),
            to_attr="logo_list",
        ),
        orders,
    ).order_by(ordering[sort], "pk")
    pagination = pagination_context(request, queryset, page_size=12)
    suppliers = list(pagination["page_obj"].object_list)
    for supplier in suppliers:
        supplier.purchase_totals = {}
        for order in getattr(supplier, "purchase_order_list", []):
            for currency, amount in order.total_by_currency().items():
                supplier.purchase_totals[currency] = supplier.purchase_totals.get(currency, 0) + amount

    metrics = base_queryset.aggregate(
        total=Count("pk"),
        businesses=Count("pk", filter=Q(kind=SupplierKind.BUSINESS)),
        individuals=Count("pk", filter=Q(kind=SupplierKind.INDIVIDUAL)),
        overseas=Count("pk", filter=Q(supplier_type=SupplierType.OVERSEAS_DEALER)),
    )
    return render(
        request,
        "suppliers/list.html",
        {
            "suppliers": suppliers,
            "supplier_types": SupplierType.choices,
            "supplier_kinds": SupplierKind.choices,
            "countries": COUNTRIES,
            "metrics": metrics,
            "q": search,
            "supplier_type": supplier_type,
            "kind": kind,
            "country": country,
            "sort": sort,
            **pagination,
        },
    )


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
    # Cars bought from this supplier: order lines that reference a vehicle.
    vehicles_bought = (
        PurchaseOrderLine.objects.filter(order__supplier=supplier)
        .exclude(vehicle=None)
        .select_related("vehicle", "order")
        .order_by("-order__order_date", "-pk")
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
            "vehicles_bought": vehicles_bought,
            "logo": supplier.logo,
            "documents": attachments,
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
