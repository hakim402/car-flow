"""Inventory views: stock list/detail, guarded status changes, internal
moves, branch transfers, and location management. All mutations go through
the services in `apps.inventory.services` (README §8.3) — views never save
stock rows directly."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission

from .aging import AGE_BUCKET_LABELS, stock_age_bucket
from .models import InventoryLocation, LocationType, StockStatus, VehicleStock
from .services import (
    ALLOWED_TRANSITIONS,
    adjust_stock_status,
    move_stock,
    transfer_stock,
)


@require_permission("inventory.view")
def stock_list(request):
    queryset = VehicleStock.objects.all()  # TenantManager filters by company.
    if request.user.branch_id:
        queryset = queryset.filter(branch_id=request.user.branch_id)
    status = request.GET.get("status", "")
    if status in StockStatus.values:
        queryset = queryset.filter(status=status)
    stock_items = list(
        queryset.select_related("vehicle", "branch", "location")
    )
    # Per-row list of legal next states so the template can offer only
    # transitions the lifecycle permits (§8.2).
    for item in stock_items:
        item.allowed_next = [
            (value, label)
            for value, label in StockStatus.choices
            if value in ALLOWED_TRANSITIONS.get(item.status, set())
        ]
    return render(
        request,
        "inventory/list.html",
        {
            "stock_items": stock_items,
            "statuses": StockStatus.choices,
            "status": status,
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
    return render(
        request,
        "inventory/location_list.html",
        {
            "locations": queryset,
            "location_types": LocationType.choices,
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
