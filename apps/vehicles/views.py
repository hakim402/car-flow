from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission
from apps.inventory.models import StockStatus

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
    from apps.purchases.models import PurchaseOrderLine

    queryset = Vehicle.objects.all()  # TenantManager filters by company.
    if request.user.branch_id:
        # Branch users see their own branch's fleet by default; the branch
        # now lives on the stock row (§8), not on the deprecated
        # Vehicle.branch mirror.
        queryset = queryset.filter(stock__branch_id=request.user.branch_id)
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if search:
        queryset = queryset.filter(vin__icontains=search) | queryset.filter(
            make__icontains=search
        ) | queryset.filter(model__icontains=search)
    if status in StockStatus.values:
        # Inventory state lives on VehicleStock (§8): filter through the
        # stock row, not the deprecated Vehicle.status mirror.
        queryset = queryset.filter(stock__status=status)
    # Card thumbnail = oldest photo; one prefetch query for the whole grid.
    photos = Prefetch(
        "documents",
        queryset=Document.objects.filter(doc_type=DocumentType.VEHICLE_PHOTO).order_by(
            "created_at", "pk"
        ),
        to_attr="photo_list",
    )
    # "Bought from" on each card = supplier of the first purchase-order line.
    purchases = Prefetch(
        "purchase_lines",
        queryset=PurchaseOrderLine.objects.select_related("order__supplier").order_by(
            "order__order_date", "pk"
        ),
        to_attr="purchase_line_list",
    )
    return render(
        request,
        "vehicles/list.html",
        {
            "vehicles": queryset.select_related("branch", "stock__branch", "stock__location").prefetch_related(
                photos, purchases
            ),
            "statuses": StockStatus.choices,
            "q": search,
            "status": status,
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
    ).order_by("order__order_date", "pk")
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
            "photos": [d for d in attachments if d.is_photo],
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
    if request.method == "POST" and form.is_valid():
        vehicle = form.save(commit=False)
        vehicle.company = company
        vehicle.save()
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
