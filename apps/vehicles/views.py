from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission
from apps.core.pagination import pagination_context
from apps.inventory.models import InventoryLocation, StockStatus, VehicleCondition
from apps.inventory.services import receive_vehicle

from .forms import VehicleForm
from .models import Vehicle


def _current_company_or_deny(request):
    company = request.user.company
    if company is None:
        # Super Admin users have no tenant; vehicle work happens per-company.
        raise PermissionDenied
    return company


@require_permission("vehicles.view")
def vehicle_list(request):
    from apps.documents.models import Document, DocumentType
    from apps.purchases.models import PurchaseOrderLine, VehicleCostLine

    base_queryset = Vehicle.objects.all()  # TenantManager filters by company.
    if request.user.branch_id:
        # Branch users see their own branch's fleet by default; the branch
        # now lives on the stock row (§8), not on the deprecated
        # Vehicle.branch mirror.
        base_queryset = base_queryset.filter(stock__branch_id=request.user.branch_id)
    queryset = base_queryset
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    make = request.GET.get("make", "").strip()
    year = request.GET.get("year", "").strip()
    condition = request.GET.get("condition", "")
    branch_id = request.GET.get("branch", "")
    location_id = request.GET.get("location", "")
    sort = request.GET.get("sort", "newest")
    if search:
        queryset = queryset.filter(
            Q(vin__icontains=search)
            | Q(make__icontains=search)
            | Q(model__icontains=search)
            | Q(plate_number__icontains=search)
            | Q(registration_number__icontains=search)
        )
    if status in StockStatus.values:
        # Inventory state lives on VehicleStock (§8): filter through the
        # stock row, not the deprecated Vehicle.status mirror.
        queryset = queryset.filter(stock__status=status)
    if make:
        queryset = queryset.filter(make__iexact=make)
    if year.isdigit():
        queryset = queryset.filter(year=int(year))
    if condition in VehicleCondition.values:
        queryset = queryset.filter(stock__condition=condition)
    if not request.user.branch_id and branch_id.isdigit():
        queryset = queryset.filter(stock__branch_id=branch_id)
    if location_id.isdigit():
        queryset = queryset.filter(stock__location_id=location_id)
    # Card thumbnail = oldest photo; one prefetch query for the whole grid.
    photos = Prefetch(
        "documents",
        queryset=Document.objects.filter(doc_type=DocumentType.VEHICLE_PHOTO).order_by(
            "created_at", "pk"
        ),
        to_attr="photo_list",
    )
    # "Bought from" on each card = supplier of the latest acquisition. This
    # remains correct when a previously sold vehicle is acquired again.
    purchases = Prefetch(
        "purchase_lines",
        queryset=PurchaseOrderLine.objects.select_related("order__supplier").order_by(
            "-order__order_date", "-pk"
        ),
        to_attr="purchase_line_list",
    )
    costs = Prefetch(
        "cost_lines",
        queryset=VehicleCostLine.objects.order_by("created_at", "pk"),
        to_attr="cost_line_list",
    )
    ordering = {
        "newest": "-created_at",
        "oldest": "created_at",
        "year_desc": "-year",
        "year_asc": "year",
        "make": "make",
        "mileage": "mileage",
    }
    sort = sort if sort in ordering else "newest"
    queryset = (
        queryset.select_related("branch", "stock__branch", "stock__location")
        .prefetch_related(photos, purchases, costs)
        .order_by(ordering[sort], "-pk")
    )
    pagination = pagination_context(request, queryset, page_size=12)
    vehicles = list(pagination["page_obj"].object_list)
    for vehicle in vehicles:
        vehicle.landed_cost = {}
        for cost in getattr(vehicle, "cost_line_list", []):
            vehicle.landed_cost[cost.currency] = vehicle.landed_cost.get(cost.currency, 0) + cost.amount

    metrics = base_queryset.aggregate(
        total=Count("pk"),
        available=Count("pk", filter=Q(stock__status=StockStatus.AVAILABLE)),
        reserved=Count("pk", filter=Q(stock__status=StockStatus.RESERVED)),
        in_process=Count(
            "pk",
            filter=Q(
                stock__status__in=[
                    StockStatus.IN_TRANSIT,
                    StockStatus.RECEIVED,
                    StockStatus.INSPECTION,
                    StockStatus.PREPARATION,
                ]
            ),
        ),
        attention=Count(
            "pk",
            filter=Q(stock__condition__in=[VehicleCondition.DAMAGED, VehicleCondition.NEEDS_REPAIR]),
        ),
    )
    company = request.user.company
    branches = company.branches.all() if company and not request.user.branch_id else ()
    locations = InventoryLocation.objects.select_related("branch").filter(active=True)
    if request.user.branch_id:
        locations = locations.filter(branch_id=request.user.branch_id)
    return render(
        request,
        "vehicles/list.html",
        {
            "vehicles": vehicles,
            "statuses": StockStatus.choices,
            "conditions": VehicleCondition.choices,
            "makes": base_queryset.order_by("make").values_list("make", flat=True).distinct(),
            "branches": branches,
            "locations": locations,
            "metrics": metrics,
            "q": search,
            "status": status,
            "make": make,
            "year": year,
            "condition": condition,
            "branch_id": branch_id,
            "location_id": location_id,
            "sort": sort,
            **pagination,
        },
    )


@require_permission("vehicles.view")
def vehicle_detail(request, pk):
    from apps.purchases.forms import VehicleCostLineForm
    from apps.purchases.services import vehicle_landed_cost

    vehicle = get_object_or_404(Vehicle, pk=pk)
    # Inventory state lives on the stock row (§8); Vehicle.status is
    # deprecated and only kept for migration history.
    stock = getattr(vehicle, "stock", None)
    attachments = vehicle.documents.all().select_related("uploaded_by")
    # Which supplier was this car bought from — via its purchase-order lines.
    purchase_lines = vehicle.purchase_lines.select_related(
        "order__supplier", "order__branch"
    ).order_by("-order__order_date", "-pk")
    return render(
        request,
        "vehicles/detail.html",
        {
            "vehicle": vehicle,
            "stock": stock,
            "cost_lines": vehicle.cost_lines.all(),
            "landed_cost": vehicle_landed_cost(vehicle),
            "cost_form": VehicleCostLineForm(),
            # Gallery + paperwork split on the photo doc type.
            "photos": [d for d in attachments if d.is_photo and d.file_exists],
            "documents": [d for d in attachments if not d.is_photo],
            "can_upload_documents": request.user.has_permission("documents.add"),
            "purchase_lines": purchase_lines,
            "source_supplier": purchase_lines[0].order.supplier if purchase_lines else None,
        },
    )


@require_permission("purchases.add")
@require_POST
def vehicle_add_cost(request, pk):
    """Append an immutable cost row (§6: corrections are new rows, never edits)."""
    from apps.purchases.forms import VehicleCostLineForm

    vehicle = get_object_or_404(Vehicle, pk=pk)
    form = VehicleCostLineForm(request.POST)
    if form.is_valid():
        line = form.save(commit=False)
        line.company = vehicle.company
        line.vehicle = vehicle
        line.created_by = request.user
        line.save()
        messages.success(request, _("Cost line added."))
    else:
        messages.error(request, _("Could not add cost line — check the form values."))
    return redirect(vehicle)


@require_permission("vehicles.add")
def vehicle_create(request):
    company = _current_company_or_deny(request)
    form = VehicleForm(request.POST or None)
    form.current_user = request.user
    if request.method == "POST" and form.is_valid():
        vehicle = form.save(commit=False)
        vehicle.company = company
        if vehicle.branch_id is None and request.user.branch_id is not None:
            vehicle.branch_id = request.user.branch_id
        vehicle.save()

        branch = vehicle.branch
        if branch is not None and branch.company_id == company.pk:
            receive_vehicle(vehicle, branch, user=request.user, notes="Vehicle created")

        messages.success(request, _("Vehicle created."))
        return redirect(vehicle)
    return render(request, "vehicles/form.html", {"form": form, "title": _("Add vehicle")})


@require_permission("vehicles.change")
def vehicle_edit(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    form = VehicleForm(request.POST or None, instance=vehicle)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Vehicle updated."))
        return redirect(vehicle)
    return render(
        request,
        "vehicles/form.html",
        {"form": form, "title": _("Edit vehicle"), "vehicle": vehicle},
    )
