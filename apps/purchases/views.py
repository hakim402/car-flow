from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission
from apps.core.pagination import pagination_context
from apps.suppliers.models import Supplier

from .forms import PurchaseOrderForm, PurchaseOrderLineForm
from .models import PurchaseOrder, PurchaseOrderLine, PurchaseStatus, PurchaseType
from .receiving import receive_order


@require_permission("purchases.view")
def order_list(request):
    base_queryset = PurchaseOrder.objects.all()  # TenantManager filters by company.
    if request.user.branch_id:
        base_queryset = base_queryset.filter(branch_id=request.user.branch_id)
    queryset = base_queryset
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    purchase_type = request.GET.get("type", "").strip()
    supplier_id = request.GET.get("supplier", "")
    branch_id = request.GET.get("branch", "")
    arrival = request.GET.get("arrival", "")
    sort = request.GET.get("sort", "newest")

    if search:
        queryset = queryset.filter(
            Q(reference__icontains=search)
            | Q(supplier__name__icontains=search)
            | Q(container_no__icontains=search)
            | Q(bill_of_lading_no__icontains=search)
            | Q(lines__vehicle__vin__icontains=search)
        ).distinct()
    if status in PurchaseStatus.values:
        queryset = queryset.filter(status=status)
    if purchase_type in PurchaseType.values:
        queryset = queryset.filter(purchase_type=purchase_type)
    if supplier_id.isdigit():
        queryset = queryset.filter(supplier_id=supplier_id)
    if not request.user.branch_id and branch_id.isdigit():
        queryset = queryset.filter(branch_id=branch_id)

    today = timezone.localdate()
    active_statuses = [
        PurchaseStatus.DRAFT,
        PurchaseStatus.ORDERED,
        PurchaseStatus.SHIPPED,
        PurchaseStatus.CUSTOMS,
    ]
    if arrival == "overdue":
        queryset = queryset.filter(status__in=active_statuses, eta__lt=today)
    elif arrival == "soon":
        queryset = queryset.filter(
            status__in=active_statuses,
            eta__gte=today,
            eta__lte=today + timedelta(days=14),
        )
    elif arrival == "no_eta":
        queryset = queryset.filter(status__in=active_statuses, eta__isnull=True)

    ordering = {
        "newest": "-order_date",
        "oldest": "order_date",
        "eta": "eta",
        "supplier": "supplier__name",
        "status": "status",
    }
    sort = sort if sort in ordering else "newest"
    queryset = (
        queryset.select_related("supplier", "branch")
        .annotate(line_count=Count("lines", distinct=True))
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=PurchaseOrderLine.objects.select_related("vehicle").order_by("pk"),
            )
        )
        .order_by(ordering[sort], "-pk")
    )
    pagination = pagination_context(request, queryset)
    orders = list(pagination["page_obj"].object_list)
    progress = {
        PurchaseStatus.DRAFT: 1,
        PurchaseStatus.ORDERED: 2,
        PurchaseStatus.SHIPPED: 3,
        PurchaseStatus.CUSTOMS: 4,
        PurchaseStatus.RECEIVED: 5,
        PurchaseStatus.CANCELLED: 0,
    }
    for order in orders:
        order.workflow_step = progress[order.status]
        if order.status == PurchaseStatus.RECEIVED:
            order.arrival_state = "received"
        elif order.status == PurchaseStatus.CANCELLED:
            order.arrival_state = "cancelled"
        elif not order.eta:
            order.arrival_state = "no_eta"
        elif order.eta < today:
            order.arrival_state = "overdue"
        elif order.eta <= today + timedelta(days=14):
            order.arrival_state = "soon"
        else:
            order.arrival_state = "on_track"

    month_start = today.replace(day=1)
    metrics = base_queryset.aggregate(
        total=Count("pk"),
        draft=Count("pk", filter=Q(status=PurchaseStatus.DRAFT)),
        in_transit=Count("pk", filter=Q(status=PurchaseStatus.SHIPPED)),
        customs=Count("pk", filter=Q(status=PurchaseStatus.CUSTOMS)),
        overdue=Count(
            "pk", filter=Q(status__in=active_statuses, eta__lt=today)
        ),
        arriving_soon=Count(
            "pk",
            filter=Q(
                status__in=active_statuses,
                eta__gte=today,
                eta__lte=today + timedelta(days=14),
            ),
        ),
        received_month=Count(
            "pk", filter=Q(status=PurchaseStatus.RECEIVED, updated_at__date__gte=month_start)
        ),
    )
    company = request.user.company
    branches = company.branches.all() if company and not request.user.branch_id else ()
    return render(
        request,
        "purchases/list.html",
        {
            "orders": orders,
            "statuses": PurchaseStatus.choices,
            "purchase_types": PurchaseType.choices,
            "suppliers": Supplier.objects.all(),
            "branches": branches,
            "metrics": metrics,
            "q": search,
            "status": status,
            "purchase_type": purchase_type,
            "supplier_id": supplier_id,
            "branch_id": branch_id,
            "arrival": arrival,
            "sort": sort,
            **pagination,
        },
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
    from apps.documents.models import Document, DocumentType

    order = get_object_or_404(PurchaseOrder, pk=pk)
    line_form = PurchaseOrderLineForm()
    active = order.status not in (PurchaseStatus.RECEIVED, PurchaseStatus.CANCELLED)
    vehicle_photos = Prefetch(
        "vehicle__documents",
        queryset=Document.objects.filter(doc_type=DocumentType.VEHICLE_PHOTO).order_by(
            "created_at", "pk"
        ),
        to_attr="photo_list",
    )
    lines = order.lines.select_related("vehicle").prefetch_related(vehicle_photos)
    order.workflow_step = {
        PurchaseStatus.DRAFT: 1,
        PurchaseStatus.ORDERED: 2,
        PurchaseStatus.SHIPPED: 3,
        PurchaseStatus.CUSTOMS: 4,
        PurchaseStatus.RECEIVED: 5,
        PurchaseStatus.CANCELLED: 0,
    }[order.status]
    today = timezone.localdate()
    if order.status == PurchaseStatus.RECEIVED:
        order.arrival_state = "received"
    elif order.status == PurchaseStatus.CANCELLED:
        order.arrival_state = "cancelled"
    elif not order.eta:
        order.arrival_state = "no_eta"
    elif order.eta < today:
        order.arrival_state = "overdue"
    elif order.eta <= today + timedelta(days=14):
        order.arrival_state = "soon"
    else:
        order.arrival_state = "on_track"
    return render(
        request,
        "purchases/detail.html",
        {
            "order": order,
            "lines": lines,
            "totals": order.total_by_currency(),
            "line_form": line_form,
            "can_receive": active,
            "can_edit": active,
            "next_status": order.next_status,
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
def order_advance(request, pk):
    """Move the order one step forward (confirm / shipped / at customs).
    RECEIVED is reached only through order_receive — it creates stock."""
    order = get_object_or_404(PurchaseOrder, pk=pk)
    next_status = order.next_status
    if next_status is None:
        messages.info(request, _("This order cannot move forward."))
    else:
        order.status = next_status
        order.save(update_fields=["status", "updated_at"])
        messages.success(
            request,
            _("Status updated: %(status)s") % {"status": order.get_status_display()},
        )
    return redirect(order)


@require_permission("purchases.change")
@require_POST
def order_receive(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    try:
        count = receive_order(order, user=request.user)
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
    else:
        messages.success(
            request,
            _("Order received (%(count)d vehicles into stock).") % {"count": count},
        )
    return redirect(order)
