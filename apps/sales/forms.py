from django import forms

from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company
from apps.customers.models import Customer
from apps.vehicles.models import Vehicle

from .models import Lead, Quotation, Reservation, Sale


class LeadForm(StyledFormMixin, forms.ModelForm):
    # Tenant-FK fields are declared, not auto-generated: the fail-closed
    # tenant manager must never run at import time; __init__ scopes them.
    customer = forms.ModelChoiceField(
        label=Lead._meta.get_field("customer").verbose_name,
        queryset=Customer.all_objects.none(),
        required=False,
    )
    vehicle_of_interest = forms.ModelChoiceField(
        label=Lead._meta.get_field("vehicle_of_interest").verbose_name,
        queryset=Vehicle.all_objects.none(),
        required=False,
    )

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
    customer = forms.ModelChoiceField(
        label=Quotation._meta.get_field("customer").verbose_name,
        queryset=Customer.all_objects.none(),
    )
    vehicle = forms.ModelChoiceField(
        label=Quotation._meta.get_field("vehicle").verbose_name,
        queryset=Vehicle.all_objects.none(),
        required=False,
    )
    lead = forms.ModelChoiceField(
        label=Quotation._meta.get_field("lead").verbose_name,
        queryset=Lead.all_objects.none(),
        required=False,
    )

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
    customer = forms.ModelChoiceField(
        label=Reservation._meta.get_field("customer").verbose_name,
        queryset=Customer.all_objects.none(),
    )
    vehicle = forms.ModelChoiceField(
        label=Reservation._meta.get_field("vehicle").verbose_name,
        queryset=Vehicle.all_objects.none(),
    )
    quotation = forms.ModelChoiceField(
        label=Reservation._meta.get_field("quotation").verbose_name,
        queryset=Quotation.all_objects.none(),
        required=False,
    )

    class Meta:
        model = Reservation
        fields = ["customer", "vehicle", "quotation", "deposit_amount", "currency", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["vehicle"].queryset = Vehicle.objects.all()
        self.fields["quotation"].queryset = Quotation.objects.all()


class SaleForm(StyledFormMixin, forms.ModelForm):
    customer = forms.ModelChoiceField(
        label=Sale._meta.get_field("customer").verbose_name,
        queryset=Customer.all_objects.none(),
    )
    vehicle = forms.ModelChoiceField(
        label=Sale._meta.get_field("vehicle").verbose_name,
        queryset=Vehicle.all_objects.none(),
    )
    reservation = forms.ModelChoiceField(
        label=Sale._meta.get_field("reservation").verbose_name,
        queryset=Reservation.all_objects.none(),
        required=False,
    )

    class Meta:
        model = Sale
        fields = ["customer", "vehicle", "reservation", "agreed_amount", "currency", "sale_date", "notes"]
        widgets = {"sale_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["vehicle"].queryset = Vehicle.objects.all()
        self.fields["reservation"].queryset = Reservation.objects.all()
