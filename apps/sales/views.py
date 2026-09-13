from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission
from apps.inventory.models import StockStatus
from apps.inventory.services import deliver_stock, release_stock, reserve_stock

from .forms import LeadForm, QuotationForm, ReservationForm, SaleForm
from .models import (
    Lead,
    LeadSource,
    LeadStatus,
    Quotation,
    QuotationStatus,
    Reservation,
    ReservationStatus,
    Sale,
    SaleStatus,
)
from .services import complete_sale, issue_invoice

PAGE_SIZE = 12


def _photo_prefetch(path):
    from apps.documents.models import Document, DocumentType

    return Prefetch(
        path,
        queryset=Document.objects.filter(
            doc_type=DocumentType.VEHICLE_PHOTO
        ).order_by("created_at", "pk"),
        to_attr="photo_list",
    )


def _pagination_context(request, records):
    page_obj = Paginator(records, PAGE_SIZE).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return {
        "page_obj": page_obj,
        "page_range": page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=1, on_ends=1
        ),
        "pagination_query": query.urlencode(),
    }


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
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    source = request.GET.get("source", "")
    sort = request.GET.get("sort", "newest")
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(phone__icontains=search)
            | Q(customer__full_name__icontains=search)
            | Q(vehicle_of_interest__vin__icontains=search)
            | Q(vehicle_of_interest__make__icontains=search)
            | Q(vehicle_of_interest__model__icontains=search)
        )
    if status in LeadStatus.values:
        queryset = queryset.filter(status=status)
    if source in LeadSource.values:
        queryset = queryset.filter(source=source)
    ordering = {
        "newest": "-created_at",
        "oldest": "created_at",
        "recently_updated": "-updated_at",
    }
    sort = sort if sort in ordering else "newest"
    queryset = (
        queryset.select_related(
            "customer", "vehicle_of_interest", "branch", "assigned_to"
        )
        .prefetch_related(_photo_prefetch("vehicle_of_interest__documents"))
        .order_by(ordering[sort])
    )
    pagination = _pagination_context(request, queryset)
    metrics = Lead.objects.aggregate(
        total=Count("pk"),
        open=Count(
            "pk",
            filter=Q(
                status__in=[
                    LeadStatus.NEW,
                    LeadStatus.CONTACTED,
                    LeadStatus.QUALIFIED,
                ]
            ),
        ),
        qualified=Count("pk", filter=Q(status=LeadStatus.QUALIFIED)),
        converted=Count("pk", filter=Q(status=LeadStatus.CONVERTED)),
    )
    return render(
        request,
        "sales/lead_list.html",
        {
            "leads": pagination["page_obj"],
            "statuses": LeadStatus.choices,
            "sources": LeadSource.choices,
            "status": status,
            "source": source,
            "q": search,
            "sort": sort,
            "metrics": metrics,
            **pagination,
        },
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
    lead = get_object_or_404(
        Lead.objects.select_related(
            "customer", "vehicle_of_interest", "branch", "assigned_to", "created_by"
        ).prefetch_related(_photo_prefetch("vehicle_of_interest__documents")),
        pk=pk,
    )
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
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    sort = request.GET.get("sort", "newest")
    if search:
        queryset = queryset.filter(
            Q(number__icontains=search)
            | Q(customer__full_name__icontains=search)
            | Q(customer__phone__icontains=search)
            | Q(vehicle__vin__icontains=search)
            | Q(vehicle__make__icontains=search)
            | Q(vehicle__model__icontains=search)
        )
    if status in QuotationStatus.values:
        queryset = queryset.filter(status=status)
    ordering = {
        "newest": "-created_at",
        "oldest": "created_at",
        "expiring": "valid_until",
        "highest_value": "-amount",
    }
    sort = sort if sort in ordering else "newest"
    queryset = (
        queryset.select_related("customer", "vehicle", "lead", "created_by")
        .prefetch_related(_photo_prefetch("vehicle__documents"))
        .order_by(ordering[sort])
    )
    pagination = _pagination_context(request, queryset)
    today = timezone.localdate()
    metrics = Quotation.objects.aggregate(
        total=Count("pk"),
        draft=Count("pk", filter=Q(status=QuotationStatus.DRAFT)),
        sent=Count("pk", filter=Q(status=QuotationStatus.SENT)),
        accepted=Count("pk", filter=Q(status=QuotationStatus.ACCEPTED)),
        expiring=Count(
            "pk",
            filter=Q(
                status__in=[QuotationStatus.DRAFT, QuotationStatus.SENT],
                valid_until__gte=today,
                valid_until__lte=today + timedelta(days=7),
            ),
        ),
    )
    return render(
        request,
        "sales/quotation_list.html",
        {
            "quotations": pagination["page_obj"],
            "statuses": QuotationStatus.choices,
            "status": status,
            "q": search,
            "sort": sort,
            "metrics": metrics,
            "today": today,
            **pagination,
        },
    )


@require_permission("sales.add")
def quotation_create(request):
    company = _company_or_deny(request)
    initial = {}
    lead_pk = request.GET.get("lead")
    if lead_pk and request.method != "POST":
        lead = get_object_or_404(Lead, pk=lead_pk)
        initial = {
            "lead": lead,
            "customer": lead.customer,
            "vehicle": lead.vehicle_of_interest,
        }
    form = QuotationForm(request.POST or None, initial=initial)
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
    quotation = get_object_or_404(
        Quotation.objects.select_related(
            "customer", "vehicle", "lead", "created_by"
        ).prefetch_related(_photo_prefetch("vehicle__documents")),
        pk=pk,
    )
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
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    sort = request.GET.get("sort", "newest")
    if search:
        queryset = queryset.filter(
            Q(customer__full_name__icontains=search)
            | Q(customer__phone__icontains=search)
            | Q(vehicle__vin__icontains=search)
            | Q(vehicle__make__icontains=search)
            | Q(vehicle__model__icontains=search)
        )
    if status in ReservationStatus.values:
        queryset = queryset.filter(status=status)
    ordering = {
        "newest": "-created_at",
        "oldest": "created_at",
        "expiring": "expires_at",
    }
    sort = sort if sort in ordering else "newest"
    queryset = (
        queryset.select_related(
            "customer", "vehicle", "vehicle__stock", "quotation", "created_by"
        )
        .prefetch_related(_photo_prefetch("vehicle__documents"))
        .order_by(ordering[sort])
    )
    pagination = _pagination_context(request, queryset)
    reservations = list(pagination["page_obj"].object_list)
    from apps.accounting.services import reservation_payment_summaries

    summaries = reservation_payment_summaries(reservations)
    for reservation in reservations:
        reservation.payment_summary = summaries[reservation.pk]
    pagination["page_obj"].object_list = reservations
    now = timezone.now()
    metrics = Reservation.objects.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(status=ReservationStatus.ACTIVE)),
        completed=Count("pk", filter=Q(status=ReservationStatus.COMPLETED)),
        expiring=Count(
            "pk",
            filter=Q(
                status=ReservationStatus.ACTIVE,
                expires_at__gt=now,
                expires_at__lte=now + timedelta(hours=48),
            ),
        ),
    )
    return render(
        request,
        "sales/reservation_list.html",
        {
            "reservations": pagination["page_obj"],
            "statuses": ReservationStatus.choices,
            "status": status,
            "q": search,
            "sort": sort,
            "metrics": metrics,
            "now": now,
            **pagination,
        },
    )


@require_permission("sales.add")
def reservation_create(request):
    company = _company_or_deny(request)
    initial = {}
    quotation_pk = request.GET.get("quotation")
    if quotation_pk and request.method != "POST":
        quotation = get_object_or_404(Quotation, pk=quotation_pk)
        initial = {
            "quotation": quotation,
            "customer": quotation.customer,
            "vehicle": quotation.vehicle,
            "currency": quotation.currency,
        }
    form = ReservationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                # Lock the stock row and require AVAILABLE first (§11): two
                # racing reservations serialize here, the loser fails.
                reserve_stock(
                    form.cleaned_data["vehicle"],
                    user=request.user,
                    notes=_("Reservation created"),
                )
                reservation = form.save(commit=False)
                reservation.company = company
                reservation.created_by = request.user
                reservation.save()
        except ValidationError as exc:
            messages.error(request, _("Vehicle cannot be reserved: %(reason)s") % {"reason": exc})
            return render(request, "sales/form.html", {"form": form, "title": _("New reservation"),
                                                       "back_url_name": "sales:reservation_list"})
        messages.success(request, _("Reservation created."))
        return redirect(reservation)
    return render(request, "sales/form.html", {"form": form, "title": _("New reservation"),
                                               "back_url_name": "sales:reservation_list"})


@require_permission("sales.view")
def reservation_detail(request, pk):
    from apps.accounting.services import reservation_payment_summary

    reservation = get_object_or_404(
        Reservation.objects.select_related(
            "customer", "vehicle", "vehicle__stock", "quotation", "created_by"
        ).prefetch_related(_photo_prefetch("vehicle__documents")),
        pk=pk,
    )
    sale = reservation.sales.select_related("customer", "vehicle").first()
    return render(
        request,
        "sales/reservation_detail.html",
        {
            "reservation": reservation,
            "sale": sale,
            "payment_summary": reservation_payment_summary(reservation),
            "can_cancel": reservation.status == ReservationStatus.ACTIVE,
            "can_record_payment": reservation.status == ReservationStatus.ACTIVE
            and request.user.has_permission("payments.add"),
            "can_create_sale": reservation.status == ReservationStatus.ACTIVE
            and sale is None
            and request.user.has_permission("sales.add"),
        },
    )


@require_permission("sales.change")
@require_POST
def reservation_cancel(request, pk):
    """Cancel an active reservation and release the vehicle (§11)."""
    reservation = get_object_or_404(Reservation, pk=pk)
    if reservation.status != ReservationStatus.ACTIVE:
        messages.error(request, _("Reservation is not active."))
        return redirect(reservation)
    with transaction.atomic():
        reservation.status = ReservationStatus.CANCELLED
        reservation.save(update_fields=["status", "updated_at"])
        release_stock(
            reservation.vehicle,
            user=request.user,
            notes=f"Reservation #{reservation.pk} cancelled",
        )
    messages.success(request, _("Reservation cancelled — vehicle released."))
    return redirect(reservation)


# --------------------------------------------------------------------------
# Sales + invoices
# --------------------------------------------------------------------------
@require_permission("sales.view")
def sale_list(request):
    queryset = Sale.objects.all()  # TenantManager filters by company.
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    sort = request.GET.get("sort", "newest")
    if search:
        queryset = queryset.filter(
            Q(customer__full_name__icontains=search)
            | Q(customer__phone__icontains=search)
            | Q(vehicle__vin__icontains=search)
            | Q(vehicle__make__icontains=search)
            | Q(vehicle__model__icontains=search)
            | Q(invoices__number__icontains=search)
        ).distinct()
    if status in SaleStatus.values:
        queryset = queryset.filter(status=status)
    ordering = {
        "newest": "-created_at",
        "oldest": "created_at",
        "sale_date": "-sale_date",
        "highest_value": "-agreed_amount",
    }
    sort = sort if sort in ordering else "newest"
    queryset = (
        queryset.select_related(
            "customer", "vehicle", "vehicle__stock", "reservation", "finance_agreement"
        )
        .prefetch_related(_photo_prefetch("vehicle__documents"))
        .order_by(ordering[sort])
    )
    pagination = _pagination_context(request, queryset)
    sales = list(pagination["page_obj"].object_list)
    from apps.accounting.services import sale_payment_summaries

    summaries = sale_payment_summaries(sales)
    for sale in sales:
        sale.payment_summary = summaries[sale.pk]
        sale.has_financing = getattr(sale, "finance_agreement", None) is not None
    pagination["page_obj"].object_list = sales
    metrics = Sale.objects.aggregate(
        total=Count("pk"),
        draft=Count("pk", filter=Q(status=SaleStatus.DRAFT)),
        completed=Count("pk", filter=Q(status=SaleStatus.COMPLETED)),
        delivered=Count("pk", filter=Q(vehicle__stock__status=StockStatus.DELIVERED)),
    )
    return render(
        request,
        "sales/sale_list.html",
        {
            "sales": pagination["page_obj"],
            "statuses": SaleStatus.choices,
            "status": status,
            "q": search,
            "sort": sort,
            "metrics": metrics,
            **pagination,
        },
    )


@require_permission("sales.add")
def sale_create(request):
    company = _company_or_deny(request)
    initial = {}
    reservation_pk = request.GET.get("reservation")
    if reservation_pk and request.method != "POST":
        reservation = get_object_or_404(Reservation, pk=reservation_pk)
        initial = {
            "reservation": reservation,
            "customer": reservation.customer,
            "vehicle": reservation.vehicle,
            "currency": reservation.currency,
        }
        if reservation.quotation_id:
            initial["agreed_amount"] = reservation.quotation.amount
    form = SaleForm(request.POST or None, initial=initial)
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
    from apps.accounting.services import sale_payment_summary

    sale = get_object_or_404(
        Sale.objects.select_related(
            "customer",
            "vehicle",
            "vehicle__stock",
            "reservation",
            "created_by",
            "finance_agreement",
        ).prefetch_related(_photo_prefetch("vehicle__documents")),
        pk=pk,
    )
    stock = getattr(sale.vehicle, "stock", None)
    finance_agreement = getattr(sale, "finance_agreement", None)
    invoice = sale.invoices.first()
    return render(
        request,
        "sales/sale_detail.html",
        {
            "sale": sale,
            "invoice": invoice,
            "stock": stock,
            "finance_agreement": finance_agreement,
            "payment_summary": sale_payment_summary(sale),
            "can_record_payment": sale.status == SaleStatus.COMPLETED
            and (
                finance_agreement is None
                or finance_agreement.status in {"draft", "pending_approval"}
            )
            and request.user.has_permission("payments.add"),
            "can_add_financing": finance_agreement is None
            and request.user.has_permission("financing.add"),
            "can_complete": sale.status == SaleStatus.DRAFT,
            "can_invoice": sale.status == SaleStatus.COMPLETED and invoice is None,
            "can_deliver": sale.status == SaleStatus.COMPLETED
            and stock is not None
            and stock.status == StockStatus.SOLD,
        },
    )


@require_permission("sales.change")
@require_POST
def sale_complete(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    try:
        completed = complete_sale(sale, user=request.user)
    except ValidationError as exc:
        messages.error(request, _("Sale could not be completed: %(reason)s") % {"reason": exc})
        return redirect(sale)
    if completed:
        messages.success(request, _("Sale completed — vehicle marked sold."))
    else:
        messages.error(request, _("Sale could not be completed (already closed?)."))
    return redirect(sale)


@require_permission("sales.change")
@require_POST
def sale_deliver(request, pk):
    """Deliver a completed sale: SOLD -> DELIVERED on the stock row (§21)."""
    sale = get_object_or_404(Sale, pk=pk)
    if sale.status != SaleStatus.COMPLETED:
        messages.error(request, _("Complete the sale before delivery."))
        return redirect(sale)
    try:
        deliver_stock(sale.vehicle, user=request.user, notes=f"Sale #{sale.pk} delivered")
    except ValidationError as exc:
        messages.error(request, _("Vehicle could not be delivered: %(reason)s") % {"reason": exc})
        return redirect(sale)
    messages.success(request, _("Vehicle delivered."))
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
