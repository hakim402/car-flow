from django import forms

from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company
from apps.customers.models import Customer
from apps.vehicles.models import Vehicle

from .models import Lead, Quotation, Reservation, Sale


class LeadForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Lead
        fields = ["name", "phone", "customer", "vehicle_of_interest", "source", "branch", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        # Tenant managers already scope these to the current company.
        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["vehicle_of_interest"].queryset = Vehicle.objects.all()
        if company is not None:
            self.fields["branch"].queryset = company.branches.all()


class QuotationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Quotation
        fields = ["customer", "vehicle", "lead", "amount", "currency", "valid_until", "notes"]
        widgets = {"valid_until": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["vehicle"].queryset = Vehicle.objects.all()
        self.fields["lead"].queryset = Lead.objects.all()


class ReservationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ["customer", "vehicle", "quotation", "deposit_amount", "currency", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["vehicle"].queryset = Vehicle.objects.all()
        self.fields["quotation"].queryset = Quotation.objects.all()


class SaleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Sale
        fields = ["customer", "vehicle", "reservation", "agreed_amount", "currency", "sale_date", "notes"]
        widgets = {"sale_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["vehicle"].queryset = Vehicle.objects.all()
        self.fields["reservation"].queryset = Reservation.objects.all()
