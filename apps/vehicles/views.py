from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission

from .forms import VehicleForm
from .models import Vehicle, VehicleStatus


def _current_company_or_deny(request):
    company = request.user.company
    if company is None:
        # Super Admin users have no tenant; vehicle work happens per-company.
        raise PermissionDenied
    return company


@require_permission("vehicles.view")
def vehicle_list(request):
    queryset = Vehicle.objects.all()  # TenantManager filters by company.
    if request.user.branch_id:
        # Branch users see their own branch's fleet by default.
        queryset = queryset.filter(branch_id=request.user.branch_id)
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if search:
        queryset = queryset.filter(vin__icontains=search) | queryset.filter(
            make__icontains=search
        ) | queryset.filter(model__icontains=search)
    if status in VehicleStatus.values:
        queryset = queryset.filter(status=status)
    return render(
        request,
        "vehicles/list.html",
        {
            "vehicles": queryset.select_related("branch"),
            "statuses": VehicleStatus.choices,
            "q": search,
            "status": status,
        },
    )


@require_permission("vehicles.view")
def vehicle_detail(request, pk):
    from apps.purchases.forms import VehicleCostLineForm
    from apps.purchases.services import vehicle_landed_cost

    vehicle = get_object_or_404(Vehicle, pk=pk)
    return render(
        request,
        "vehicles/detail.html",
        {
            "vehicle": vehicle,
            "cost_lines": vehicle.cost_lines.all(),
            "landed_cost": vehicle_landed_cost(vehicle),
            "cost_form": VehicleCostLineForm(),
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
