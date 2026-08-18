from django import forms

from apps.core.forms import StyledFormMixin
from apps.customers.models import Customer
from apps.vehicles.models import Vehicle

from .models import Document


class DocumentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Document
        fields = ["doc_type", "title", "vehicle", "customer", "file"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Tenant managers already scope these to the current company.
        self.fields["vehicle"].queryset = Vehicle.objects.all()
        self.fields["customer"].queryset = Customer.objects.all()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("vehicle") and not cleaned.get("customer"):
            raise forms.ValidationError(_("Attach the document to a vehicle or a customer."))
        return cleaned
