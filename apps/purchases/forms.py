from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company
from apps.suppliers.models import Supplier
from apps.vehicles.models import Vehicle

from .models import PurchaseOrder, PurchaseOrderLine, PurchaseType, VehicleCostLine


class PurchaseOrderForm(StyledFormMixin, forms.ModelForm):
    # Declared, not auto-generated: the tenant manager is fail-closed and
    # must never run at import time; __init__ scopes it to the company.
    supplier = forms.ModelChoiceField(
        label=PurchaseOrder._meta.get_field("supplier").verbose_name,
        queryset=Supplier.all_objects.none(),
    )

    class Meta:
        model = PurchaseOrder
        fields = [
            "reference",
            "supplier",
            "branch",
            "order_date",
            "purchase_type",
            "origin_country",
            "incoterms",
            "shipping_method",
            "bill_of_lading_no",
            "container_no",
            "shipped_date",
            "eta",
            "notes",
        ]
        widgets = {
            "order_date": forms.DateInput(attrs={"type": "date"}),
            "shipped_date": forms.DateInput(attrs={"type": "date"}),
            "eta": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        # Tenant managers already scope these to the current company.
        self.fields["supplier"].queryset = Supplier.objects.all()
        if company is not None:
            self.fields["branch"].queryset = company.branches.all()

    def clean(self):
        cleaned = super().clean()
        # Import orders must say where the vehicles come from — that is the
        # whole point of the import workflow.
        if cleaned.get("purchase_type") == PurchaseType.IMPORT and not cleaned.get(
            "origin_country"
        ):
            self.add_error("origin_country", forms.ValidationError(
                _("Origin country is required for import orders."),
                code="origin_required",
            ))
        return cleaned


class PurchaseOrderLineForm(StyledFormMixin, forms.ModelForm):
    # Same fail-closed rationale as PurchaseOrderForm.supplier.
    vehicle = forms.ModelChoiceField(
        label=PurchaseOrderLine._meta.get_field("vehicle").verbose_name,
        queryset=Vehicle.all_objects.none(),
    )

    class Meta:
        model = PurchaseOrderLine
        fields = ["description", "vehicle", "amount", "currency"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.all()


class VehicleCostLineForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = VehicleCostLine
        fields = ["cost_type", "amount", "currency", "description"]
