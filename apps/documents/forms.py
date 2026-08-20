from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.customers.models import Customer
from apps.suppliers.models import Supplier
from apps.vehicles.models import Vehicle

from .models import (
    CUSTOMER_DOC_TYPES,
    SUPPLIER_DOC_TYPES,
    VEHICLE_DOC_TYPES,
    Document,
    DocumentType,
)


class DocumentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Document
        fields = ["doc_type", "title", "vehicle", "customer", "supplier", "file"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Tenant managers already scope these to the current company.
        self.fields["vehicle"].queryset = Vehicle.objects.all()
        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["supplier"].queryset = Supplier.objects.all()

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get("vehicle") or cleaned.get("customer") or cleaned.get("supplier")):
            raise forms.ValidationError(
                _("Attach the document to a vehicle, a customer or a supplier.")
            )
        return cleaned


class VehicleDocumentForm(DocumentForm):
    """Upload box on the vehicle detail page: the vehicle is fixed (hidden
    input), customer is irrelevant, and only vehicle-related types apply."""

    def __init__(self, *args, vehicle=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.vehicle = vehicle
        del self.fields["customer"]
        del self.fields["supplier"]
        self.fields["vehicle"].widget = forms.HiddenInput()
        if vehicle is not None:
            self.fields["vehicle"].initial = vehicle
        self.fields["doc_type"].choices = [
            choice
            for choice in DocumentType.choices
            if choice[0] in VEHICLE_DOC_TYPES
        ]

    def clean(self):
        # Skip DocumentForm.clean: customer is gone and vehicle is enforced
        # by the locked hidden field.
        return super(DocumentForm, self).clean()


class CustomerDocumentForm(DocumentForm):
    """Upload box on the customer detail page: the customer is fixed (hidden
    input), vehicle is irrelevant, and identity/bill types apply."""

    def __init__(self, *args, customer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        del self.fields["vehicle"]
        del self.fields["supplier"]
        self.fields["customer"].widget = forms.HiddenInput()
        if customer is not None:
            self.fields["customer"].initial = customer
        self.fields["doc_type"].choices = [
            choice
            for choice in DocumentType.choices
            if choice[0] in CUSTOMER_DOC_TYPES
        ]

    def clean(self):
        # Skip DocumentForm.clean: vehicle is gone and customer is enforced
        # by the locked hidden field.
        return super(DocumentForm, self).clean()


class SupplierDocumentForm(DocumentForm):
    """Upload box on the supplier detail page: the supplier is fixed (hidden
    input); only supplier types (logo, license, paperwork) apply."""

    def __init__(self, *args, supplier=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.supplier = supplier
        del self.fields["vehicle"]
        del self.fields["customer"]
        self.fields["supplier"].widget = forms.HiddenInput()
        if supplier is not None:
            self.fields["supplier"].initial = supplier
        self.fields["doc_type"].choices = [
            choice
            for choice in DocumentType.choices
            if choice[0] in SUPPLIER_DOC_TYPES
        ]

    def clean(self):
        # Skip DocumentForm.clean: vehicle/customer are gone and supplier is
        # enforced by the locked hidden field.
        return super(DocumentForm, self).clean()
