"""Inventory views: stock list/detail, guarded status changes, internal
moves, branch transfers, and location management. All mutations go through
the services in `apps.inventory.services` (README §8.3) — views never save
stock rows directly."""
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Min, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission
from apps.core.pagination import pagination_context

from .aging import AGE_BUCKET_LABELS, stock_age_bucket
from .models import InventoryLocation, LocationType, StockStatus, VehicleStock
from .services import (
    ALLOWED_TRANSITIONS,
    adjust_stock_status,
    move_stock,
    transfer_stock,
)


MANUAL_STATUS_TARGETS = {
    StockStatus.INSPECTION,
    StockStatus.PREPARATION,
    StockStatus.AVAILABLE,
}


@require_permission("inventory.view")
def stock_list(request):
    from apps.documents.models import Document, DocumentType
    from apps.purchases.models import VehicleCostLine

    base_queryset = VehicleStock.objects.all()  # TenantManager filters by company.
    if request.user.branch_id:
        base_queryset = base_queryset.filter(branch_id=request.user.branch_id)

    queryset = base_queryset
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    condition = request.GET.get("condition", "")
    branch_id = request.GET.get("branch", "")
    location_id = request.GET.get("location", "")
    age = request.GET.get("age", "")
    sort = request.GET.get("sort", "newest")

    if search:
        queryset = queryset.filter(
            Q(vehicle__vin__icontains=search)
            | Q(vehicle__make__icontains=search)
            | Q(vehicle__model__icontains=search)
            | Q(vehicle__plate_number__icontains=search)
            | Q(lot_code__icontains=search)
        )
    if status in StockStatus.values:
        queryset = queryset.filter(status=status)
    if condition in dict(VehicleStock._meta.get_field("condition").choices):
        queryset = queryset.filter(condition=condition)
    if not request.user.branch_id and branch_id.isdigit():
        queryset = queryset.filter(branch_id=branch_id)
    if location_id.isdigit():
        queryset = queryset.filter(location_id=location_id)

    now = timezone.now()
    age_filters = {
        "0_30": Q(received_at__gte=now - timedelta(days=30)),
        "31_60": Q(received_at__lt=now - timedelta(days=30), received_at__gte=now - timedelta(days=60)),
        "61_90": Q(received_at__lt=now - timedelta(days=60), received_at__gte=now - timedelta(days=90)),
        "90_plus": Q(received_at__lt=now - timedelta(days=90)),
    }
    if age in age_filters:
        queryset = queryset.filter(age_filters[age])

    ordering = {
        "newest": "-received_at",
        "oldest": "received_at",
        "vehicle": "vehicle__make",
        "status": "status",
    }
    sort = sort if sort in ordering else "newest"
    photos = Prefetch(
        "vehicle__documents",
        queryset=Document.objects.filter(doc_type=DocumentType.VEHICLE_PHOTO).order_by(
            "created_at", "pk"
        ),
        to_attr="photo_list",
    )
    costs = Prefetch(
        "vehicle__cost_lines",
        queryset=VehicleCostLine.objects.order_by("created_at", "pk"),
        to_attr="cost_line_list",
    )
    queryset = (
        queryset.select_related("vehicle", "branch", "location")
        .prefetch_related(photos, costs)
        .order_by(ordering[sort], "-pk")
    )
    pagination = pagination_context(request, queryset)
    stock_items = list(pagination["page_obj"].object_list)
    # Per-row list of legal next states so the template can offer only
    # transitions the lifecycle permits (§8.2).
    for item in stock_items:
        item.allowed_next = [
            (value, label)
            for value, label in StockStatus.choices
            if value in ALLOWED_TRANSITIONS.get(item.status, set())
            and value in MANUAL_STATUS_TARGETS
            and item.status in {
                StockStatus.RECEIVED,
                StockStatus.INSPECTION,
                StockStatus.PREPARATION,
            }
        ]
        item.landed_cost = {}
        for cost in getattr(item.vehicle, "cost_line_list", []):
            item.landed_cost[cost.currency] = item.landed_cost.get(cost.currency, 0) + cost.amount

    metrics = base_queryset.aggregate(
        total=Count("pk"),
        available=Count("pk", filter=Q(status=StockStatus.AVAILABLE)),
        reserved=Count("pk", filter=Q(status=StockStatus.RESERVED)),
        in_transit=Count("pk", filter=Q(status=StockStatus.IN_TRANSIT)),
        preparation=Count(
            "pk", filter=Q(status__in=[StockStatus.INSPECTION, StockStatus.PREPARATION])
        ),
        sold_pending=Count("pk", filter=Q(status=StockStatus.SOLD)),
        aging=Count(
            "pk",
            filter=Q(received_at__lt=now - timedelta(days=90))
            & ~Q(status__in=[StockStatus.SOLD, StockStatus.DELIVERED]),
        ),
    )
    active_stock = base_queryset.exclude(status__in=[StockStatus.SOLD, StockStatus.DELIVERED])
    inventory_value = list(
        VehicleCostLine.objects.filter(vehicle__stock__in=active_stock)
        .values("currency")
        .annotate(amount=Sum("amount"))
        .order_by("currency")
    )
    company = request.user.company
    branches = company.branches.all() if company and not request.user.branch_id else ()
    locations = InventoryLocation.objects.select_related("branch").filter(active=True)
    if request.user.branch_id:
        locations = locations.filter(branch_id=request.user.branch_id)
    return render(
        request,
        "inventory/list.html",
        {
            "stock_items": stock_items,
            "statuses": StockStatus.choices,
            "conditions": VehicleStock._meta.get_field("condition").choices,
            "branches": branches,
            "locations": locations,
            "metrics": metrics,
            "inventory_value": inventory_value,
            "can_change": request.user.has_permission("inventory.change"),
            "q": search,
            "status": status,
            "condition": condition,
            "branch_id": branch_id,
            "location_id": location_id,
            "age": age,
            "sort": sort,
            **pagination,
        },
    )


@require_permission("inventory.view")
def stock_detail(request, pk):
    stock = get_object_or_404(VehicleStock, pk=pk)
    movements = stock.vehicle.movements.select_related(
        "from_branch", "to_branch", "from_location", "to_location", "performed_by"
    )
    company = request.user.company
    branches = company.branches.all() if company is not None else ()
    locations = InventoryLocation.objects.filter(active=True)
    age_bucket = stock_age_bucket(stock)
    return render(
        request,
        "inventory/detail.html",
        {
            "stock": stock,
            "movements": movements,
            "branches": branches,
            "locations": locations,
            "age_bucket_label": AGE_BUCKET_LABELS.get(age_bucket),
        },
    )


@require_permission("inventory.change")
@require_POST
def stock_update_status(request, pk):
    """Guarded manual lifecycle step, recorded as an ADJUSTMENT movement."""
    stock = get_object_or_404(VehicleStock, pk=pk)
    new_status = request.POST.get("status", "")
    if new_status not in StockStatus.values:
        messages.error(request, _("Unknown status."))
        return redirect("inventory:list")
    allowed = ALLOWED_TRANSITIONS.get(stock.status, set())
    if new_status not in allowed or new_status not in MANUAL_STATUS_TARGETS or stock.status not in {
        StockStatus.RECEIVED,
        StockStatus.INSPECTION,
        StockStatus.PREPARATION,
    }:
        messages.error(
            request,
            _("Use the reservation, sale, delivery, or return workflow for this status change."),
        )
        return redirect("inventory:list")
    try:
        adjust_stock_status(
            stock,
            new_status,
            user=request.user,
            notes=_("Manual status change"),
        )
    except ValidationError as exc:
        messages.error(request, _("Status change rejected: %(reason)s") % {"reason": exc})
        return redirect("inventory:list")
    messages.success(request, _("Stock status updated."))
    return redirect("inventory:list")


@require_permission("inventory.move")
@require_POST
def stock_move(request, pk):
    """Internal move between locations of the same branch."""
    stock = get_object_or_404(VehicleStock, pk=pk)
    try:
        location = InventoryLocation.objects.get(pk=request.POST.get("location", ""))
    except (InventoryLocation.DoesNotExist, ValueError):
        messages.error(request, _("Choose a valid location."))
        return redirect("inventory:stock_detail", pk=stock.pk)
    try:
        move_stock(stock, location, user=request.user, notes=request.POST.get("notes", ""))
    except ValidationError as exc:
        messages.error(request, _("Move rejected: %(reason)s") % {"reason": exc})
        return redirect("inventory:stock_detail", pk=stock.pk)
    messages.success(request, _("Vehicle moved."))
    return redirect("inventory:stock_detail", pk=stock.pk)


@require_permission("inventory.transfer")
@require_POST
def stock_transfer(request, pk):
    """Transfer a vehicle to another branch (optionally a location there)."""
    stock = get_object_or_404(VehicleStock, pk=pk)
    company = request.user.company
    if company is None:
        messages.error(request, _("Transfers happen per company."))
        return redirect("inventory:stock_detail", pk=stock.pk)
    try:
        branch = company.branches.get(pk=request.POST.get("branch", ""))
    except (company.branches.model.DoesNotExist, ValueError):
        messages.error(request, _("Choose a valid branch."))
        return redirect("inventory:stock_detail", pk=stock.pk)
    location = None
    location_pk = request.POST.get("location", "")
    if location_pk:
        try:
            location = InventoryLocation.objects.get(pk=location_pk)
        except (InventoryLocation.DoesNotExist, ValueError):
            messages.error(request, _("Choose a valid location."))
            return redirect("inventory:stock_detail", pk=stock.pk)
    try:
        transfer_stock(
            stock,
            branch,
            user=request.user,
            to_location=location,
            notes=request.POST.get("notes", ""),
        )
    except ValidationError as exc:
        messages.error(request, _("Transfer rejected: %(reason)s") % {"reason": exc})
        return redirect("inventory:stock_detail", pk=stock.pk)
    messages.success(request, _("Vehicle transferred."))
    return redirect("inventory:stock_detail", pk=stock.pk)


@require_permission("inventory.view")
def location_list(request):
    queryset = InventoryLocation.objects.select_related("branch")
    search = request.GET.get("q", "").strip()
    branch_id = request.GET.get("branch", "")
    location_type = request.GET.get("type", "")
    state = request.GET.get("state", "")
    sort = request.GET.get("sort", "branch")

    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(code__icontains=search)
            | Q(branch__name__icontains=search)
        )
    if branch_id.isdigit():
        queryset = queryset.filter(branch_id=branch_id)
    if location_type in LocationType.values:
        queryset = queryset.filter(type=location_type)
    if state == "active":
        queryset = queryset.filter(active=True)
    elif state == "inactive":
        queryset = queryset.filter(active=False)

    ordering = {
        "branch": ("branch__name", "name"),
        "name": ("name",),
        "busiest": ("-vehicle_count", "branch__name", "name"),
    }
    sort = sort if sort in ordering else "branch"
    queryset = queryset.annotate(
        vehicle_count=Count("stock"),
        available_count=Count("stock", filter=Q(stock__status=StockStatus.AVAILABLE)),
        reserved_count=Count("stock", filter=Q(stock__status=StockStatus.RESERVED)),
        preparation_count=Count(
            "stock",
            filter=Q(stock__status__in=[StockStatus.INSPECTION, StockStatus.PREPARATION]),
        ),
        sold_count=Count("stock", filter=Q(stock__status=StockStatus.SOLD)),
        oldest_received=Min(
            "stock__received_at",
            filter=~Q(stock__status__in=[StockStatus.SOLD, StockStatus.DELIVERED]),
        ),
    ).order_by(*ordering[sort], "pk")
    pagination = pagination_context(request, queryset, page_size=12)
    locations = list(pagination["page_obj"].object_list)
    for location in locations:
        location.oldest_age = (
            (timezone.localdate() - location.oldest_received.date()).days
            if location.oldest_received
            else None
        )
    all_locations = InventoryLocation.objects.all()
    metrics = all_locations.aggregate(
        total=Count("pk"),
        active_count=Count("pk", filter=Q(active=True)),
        inactive_count=Count("pk", filter=Q(active=False)),
        occupied=Count("pk", filter=Q(stock__isnull=False), distinct=True),
    )
    company = request.user.company
    branches = company.branches.all() if company is not None else ()
    return render(
        request,
        "inventory/location_list.html",
        {
            "locations": locations,
            "location_types": LocationType.choices,
            "branches": branches,
            "metrics": metrics,
            "q": search,
            "branch_id": branch_id,
            "location_type": location_type,
            "state": state,
            "sort": sort,
            **pagination,
        },
    )


@require_permission("inventory.add")
@require_POST
def location_create(request):
    company = request.user.company
    if company is None:
        messages.error(request, _("Locations are created per company."))
        return redirect("inventory:location_list")
    name = (request.POST.get("name") or "").strip()
    code = (request.POST.get("code") or "").strip()
    try:
        branch = company.branches.get(pk=request.POST.get("branch", ""))
    except (company.branches.model.DoesNotExist, ValueError):
        messages.error(request, _("Choose a valid branch."))
        return redirect("inventory:location_list")
    if not name:
        messages.error(request, _("Location name is required."))
        return redirect("inventory:location_list")
    location_type = request.POST.get("type", LocationType.OTHER)
    if location_type not in LocationType.values:
        location_type = LocationType.OTHER
    InventoryLocation.objects.create(
        company=company,
        branch=branch,
        name=name,
        type=location_type,
        code=code,
    )
    messages.success(request, _("Location created."))
    return redirect("inventory:location_list")


@require_permission("inventory.change")
@require_POST
def location_toggle(request, pk):
    location = get_object_or_404(InventoryLocation, pk=pk)
    location.active = not location.active
    location.save(update_fields=["active"])
    return redirect("inventory:location_list")
