from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.decorators import require_permission

from .forms import CustomerDocumentForm, DocumentForm, VehicleDocumentForm
from .models import Document


@require_permission("documents.view")
def document_list(request):
    documents = Document.objects.all().select_related(  # TenantManager scopes.
        "vehicle", "customer"
    )
    return render(request, "documents/list.html", {"documents": documents})


@require_permission("documents.add")
def document_upload(request, vehicle_pk=None, customer_pk=None):
    if request.user.company is None:
        raise PermissionDenied
    vehicle = None
    customer = None
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
        return redirect("documents:list")
    if vehicle is not None:
        title = _("Add photo / document to %(vehicle)s") % {"vehicle": vehicle}
    elif customer is not None:
        title = _("Add photo / document for %(customer)s") % {"customer": customer}
    else:
        title = _("Upload document")
    return render(
        request,
        "documents/form.html",
        {"form": form, "title": title, "vehicle": vehicle, "customer": customer},
    )
