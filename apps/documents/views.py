from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.decorators import require_permission
from apps.core.pagination import pagination_context

from .forms import (
    CustomerDocumentForm,
    DocumentForm,
    FinancingDocumentForm,
    SupplierDocumentForm,
    VehicleDocumentForm,
)
from .models import Document, DocumentType


@require_permission("documents.view")
def document_list(request):
    base_queryset = Document.objects.all().select_related(  # TenantManager scopes.
        "vehicle", "customer", "supplier", "finance_agreement", "uploaded_by"
    )
    metrics = {
        "total": base_queryset.count(),
        "photos": base_queryset.filter(
            doc_type__in=(
                DocumentType.VEHICLE_PHOTO,
                DocumentType.CUSTOMER_PHOTO,
                DocumentType.SUPPLIER_PHOTO,
                DocumentType.SUPPLIER_LOGO,
            )
        ).count(),
        "vehicles": base_queryset.filter(vehicle__isnull=False).count(),
        "customers": base_queryset.filter(customer__isnull=False).count(),
    }
    documents = base_queryset
    q = request.GET.get("q", "").strip()
    if q:
        documents = documents.filter(
            Q(title__icontains=q)
            | Q(file__icontains=q)
            | Q(vehicle__vin__icontains=q)
            | Q(vehicle__make__icontains=q)
            | Q(vehicle__model__icontains=q)
            | Q(customer__full_name__icontains=q)
            | Q(supplier__name__icontains=q)
            | Q(finance_agreement__number__icontains=q)
        )
    doc_type = request.GET.get("type", "")
    if doc_type in DocumentType.values:
        documents = documents.filter(doc_type=doc_type)
    target = request.GET.get("target", "")
    target_fields = {
        "vehicle": "vehicle__isnull",
        "customer": "customer__isnull",
        "supplier": "supplier__isnull",
        "financing": "finance_agreement__isnull",
    }
    if target in target_fields:
        documents = documents.filter(**{target_fields[target]: False})
    page = pagination_context(request, documents, page_size=15)
    return render(
        request,
        "documents/list.html",
        {
            **page,
            "documents": page["page_obj"],
            "metrics": metrics,
            "document_types": DocumentType.choices,
            "filters": request.GET,
            "can_add": request.user.has_permission("documents.add"),
        },
    )


@require_permission("documents.add")
def document_upload(request, vehicle_pk=None, customer_pk=None, supplier_pk=None, agreement_pk=None):
    if request.user.company is None:
        raise PermissionDenied
    vehicle = None
    customer = None
    supplier = None
    agreement = None
    if vehicle_pk is not None:
        # TenantManager scopes the lookup — another company's vehicle 404s.
        from apps.vehicles.models import Vehicle

        vehicle = get_object_or_404(Vehicle, pk=vehicle_pk)
        form = VehicleDocumentForm(
            request.POST or None, request.FILES or None, vehicle=vehicle
        )
    elif customer_pk is not None:
        # TenantManager scopes the lookup — another company's customer 404s.
        from apps.customers.models import Customer

        customer = get_object_or_404(Customer, pk=customer_pk)
        form = CustomerDocumentForm(
            request.POST or None, request.FILES or None, customer=customer
        )
    elif supplier_pk is not None:
        # TenantManager scopes the lookup — another company's supplier 404s.
        from apps.suppliers.models import Supplier

        supplier = get_object_or_404(Supplier, pk=supplier_pk)
        form = SupplierDocumentForm(
            request.POST or None, request.FILES or None, supplier=supplier
        )
    elif agreement_pk is not None:
        from apps.financing.models import FinanceAgreement

        agreement = get_object_or_404(FinanceAgreement, pk=agreement_pk)
        form = FinancingDocumentForm(
            request.POST or None, request.FILES or None, agreement=agreement
        )
    else:
        form = DocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.company = request.user.company
        document.uploaded_by = request.user
        document.save()
        messages.success(request, _("Document uploaded."))
        if vehicle is not None:
            return redirect(vehicle)
        if customer is not None:
            return redirect(customer)
        if supplier is not None:
            return redirect(supplier)
        if agreement is not None:
            return redirect(agreement)
        return redirect("documents:list")
    if vehicle is not None:
        title = _("Add photo / document to %(vehicle)s") % {"vehicle": vehicle}
    elif customer is not None:
        title = _("Add photo / document for %(customer)s") % {"customer": customer}
    elif supplier is not None:
        title = _("Add logo / document for %(supplier)s") % {"supplier": supplier}
    elif agreement is not None:
        title = _("Add document for %(agreement)s") % {"agreement": agreement}
    else:
        title = _("Upload document")
    return render(
        request,
        "documents/form.html",
        {
            "form": form,
            "title": title,
            "vehicle": vehicle,
            "customer": customer,
            "supplier": supplier,
            "agreement": agreement,
        },
    )
