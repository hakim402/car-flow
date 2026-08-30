from django import forms

from apps.core.forms import StyledFormMixin

from .models import Supplier


class SupplierForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = [
            "name",
            "kind",
            "supplier_type",
            "national_id",
            "country",
            "contact_person",
            "phone",
            "email",
            "address",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Kabul Auto Exchange"}),
            "national_id": forms.TextInput(attrs={"placeholder": "Tazkera / passport / registration number"}),
            "contact_person": forms.TextInput(attrs={"placeholder": "Full name of main contact"}),
            "phone": forms.TextInput(attrs={"placeholder": "+93 700 000 000"}),
            "email": forms.EmailInput(attrs={"placeholder": "accounts@supplier.com"}),
            "address": forms.Textarea(attrs={"rows": 3, "placeholder": "Street address, city, and office location"}),
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Any preferred payment terms, pricing notes, or business notes..."}),
        }
