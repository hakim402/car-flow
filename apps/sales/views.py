from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission
from apps.vehicles.models import VehicleStatus

from .forms import LeadForm, QuotationForm, ReservationForm, SaleForm
from .models import (
    Lead,
    LeadStatus,
    Quotation,
    QuotationStatus,
    Reservation,
    Sale,
    SaleStatus,
)
from .services import complete_sale, issue_invoice


def _company_or_deny(request):
    company = request.user.company
    if company is None:
        # Super Admin users have no tenant; sales happen per-company.
        raise PermissionDenied
    return company


# --------------------------------------------------------------------------
# Leads
# --------------------------------------------------------------------------
@require_permission("sales.view")
def lead_list(request):
    queryset = Lead.objects.all()  # TenantManager filters by company.
    status = request.GET.get("status", "")
    if status in LeadStatus.values:
        queryset = queryset.filter(status=status)
    return render(
        request,
        "sales/lead_list.html",
        {"leads": queryset.select_related("customer", "vehicle_of_interest"),
         "statuses": LeadStatus.choices,
         "status": status},
    )


@require_permission("sales.add")
def lead_create(request):
    company = _company_or_deny(request)
    form = LeadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lead = form.save(commit=False)
        lead.company = company
        lead.created_by = request.user
        lead.save()
        messages.success(request, _("Lead created."))
        return redirect(lead)
    return render(request, "sales/form.html", {"form": form, "title": _("New lead"),
                                               "back_url_name": "sales:lead_list"})


@require_permission("sales.view")
def lead_detail(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    return render(request, "sales/lead_detail.html",
                  {"lead": lead, "statuses": LeadStatus.choices})


@require_permission("sales.change")
@require_POST
def lead_update_status(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    status = request.POST.get("status", "")
    if status in LeadStatus.values:
        lead.status = status
        lead.save(update_fields=["status", "updated_at"])
        messages.success(request, _("Lead status updated."))
    else:
        messages.error(request, _("Unknown status."))
    return redirect(lead)


# --------------------------------------------------------------------------
# Quotations
# --------------------------------------------------------------------------
@require_permission("sales.view")
def quotation_list(request):
    queryset = Quotation.objects.all()  # TenantManager filters by company.
    return render(
        request,
        "sales/quotation_list.html",
        {"quotations": queryset.select_related("customer", "vehicle")},
    )


@require_permission("sales.add")
def quotation_create(request):
    company = _company_or_deny(request)
    form = QuotationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        quotation = form.save(commit=False)
        quotation.company = company
        quotation.created_by = request.user
        quotation.save()
        messages.success(request, _("Quotation created."))
        return redirect(quotation)
    return render(request, "sales/form.html", {"form": form, "title": _("New quotation"),
                                               "back_url_name": "sales:quotation_list"})


@require_permission("sales.view")
def quotation_detail(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    return render(request, "sales/quotation_detail.html",
                  {"quotation": quotation, "statuses": QuotationStatus.choices})


@require_permission("sales.change")
@require_POST
def quotation_update_status(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    status = request.POST.get("status", "")
    if status in QuotationStatus.values:
        quotation.status = status
        quotation.save(update_fields=["status", "updated_at"])
        messages.success(request, _("Quotation status updated."))
    else:
        messages.error(request, _("Unknown status."))
    return redirect(quotation)


# --------------------------------------------------------------------------
# Reservations
# --------------------------------------------------------------------------
@require_permission("sales.view")
def reservation_list(request):
    queryset = Reservation.objects.all()  # TenantManager filters by company.
    return render(
        request,
        "sales/reservation_list.html",
        {"reservations": queryset.select_related("customer", "vehicle")},
    )


@require_permission("sales.add")
def reservation_create(request):
    company = _company_or_deny(request)
    form = ReservationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            reservation = form.save(commit=False)
            reservation.company = company
            reservation.created_by = request.user
            reservation.save()
            # Reserving flips the vehicle so it cannot be double-sold.
            vehicle = reservation.vehicle
            if vehicle.status == VehicleStatus.IN_STOCK:
                vehicle.status = VehicleStatus.RESERVED
                vehicle.save(update_fields=["status", "updated_at"])
        messages.success(request, _("Reservation created."))
        return redirect("sales:reservation_list")
    return render(request, "sales/form.html", {"form": form, "title": _("New reservation"),
                                               "back_url_name": "sales:reservation_list"})


# --------------------------------------------------------------------------
# Sales + invoices
# --------------------------------------------------------------------------
@require_permission("sales.view")
def sale_list(request):
    queryset = Sale.objects.all()  # TenantManager filters by company.
    return render(
        request,
        "sales/sale_list.html",
        {"sales": queryset.select_related("customer", "vehicle")},
    )


@require_permission("sales.add")
def sale_create(request):
    company = _company_or_deny(request)
    form = SaleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        sale = form.save(commit=False)
        sale.company = company
        sale.created_by = request.user
        sale.save()
        messages.success(request, _("Sale created — complete it to close the deal."))
        return redirect(sale)
    return render(request, "sales/form.html", {"form": form, "title": _("New sale"),
                                               "back_url_name": "sales:sale_list"})


@require_permission("sales.view")
def sale_detail(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    return render(
        request,
        "sales/sale_detail.html",
        {
            "sale": sale,
            "invoice": sale.invoices.first(),
            "can_complete": sale.status == SaleStatus.DRAFT,
            "can_invoice": sale.status == SaleStatus.COMPLETED and not sale.invoices.exists(),
        },
    )


@require_permission("sales.change")
@require_POST
def sale_complete(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    if complete_sale(sale, user=request.user):
        messages.success(request, _("Sale completed — vehicle marked sold."))
    else:
        messages.error(request, _("Sale could not be completed (already closed?)."))
    return redirect(sale)


@require_permission("sales.change")
@require_POST
def sale_issue_invoice(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    if sale.status != SaleStatus.COMPLETED:
        messages.error(request, _("Complete the sale before issuing the invoice."))
    else:
        invoice = issue_invoice(sale, user=request.user)
        messages.success(request, _("Invoice %(number)s issued.") % {"number": invoice.number})
    return redirect(sale)
