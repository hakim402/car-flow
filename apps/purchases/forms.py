from django import forms

from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company
from apps.suppliers.models import Supplier
from apps.vehicles.models import Vehicle

from .models import PurchaseOrder, PurchaseOrderLine, VehicleCostLine


class PurchaseOrderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["reference", "supplier", "branch", "order_date", "notes"]
        widgets = {"order_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        # Tenant managers already scope these to the current company.
        self.fields["supplier"].queryset = Supplier.objects.all()
        if company is not None:
            self.fields["branch"].queryset = company.branches.all()


class PurchaseOrderLineForm(StyledFormMixin, forms.ModelForm):
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
