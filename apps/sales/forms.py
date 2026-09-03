from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company
from apps.customers.models import Customer
from apps.inventory.models import StockStatus
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
        fields = [
            "name",
            "phone",
            "customer",
            "vehicle_of_interest",
            "source",
            "branch",
            "assigned_to",
            "lost_reason",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is not None:
            self.fields["customer"].queryset = Customer.objects.filter(company=company)
            self.fields["vehicle_of_interest"].queryset = Vehicle.objects.filter(company=company)
            self.fields["branch"].queryset = company.branches.all()
            self.fields["assigned_to"].queryset = User.objects.filter(company=company)
        else:
            self.fields["customer"].queryset = Customer.all_objects.all()
            self.fields["vehicle_of_interest"].queryset = Vehicle.all_objects.all()
            self.fields["branch"].queryset = Vehicle.all_objects.none()
            self.fields["assigned_to"].queryset = User.objects.none()


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
        fields = ["number", "customer", "vehicle", "lead", "amount", "currency", "valid_until", "notes"]
        widgets = {"valid_until": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is not None:
            self.fields["customer"].queryset = Customer.objects.filter(company=company)
            self.fields["vehicle"].queryset = Vehicle.objects.filter(company=company)
            self.fields["lead"].queryset = Lead.objects.filter(company=company)
        else:
            self.fields["customer"].queryset = Customer.all_objects.all()
            self.fields["vehicle"].queryset = Vehicle.all_objects.all()
            self.fields["lead"].queryset = Lead.all_objects.all()


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
        fields = ["customer", "vehicle", "quotation", "deposit_amount", "currency", "expires_at", "notes"]
        widgets = {"expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is not None:
            self.fields["customer"].queryset = Customer.objects.filter(company=company)
            self.fields["vehicle"].queryset = Vehicle.objects.filter(company=company)
            self.fields["quotation"].queryset = Quotation.objects.filter(company=company)
        else:
            self.fields["customer"].queryset = Customer.all_objects.all()
            self.fields["vehicle"].queryset = Vehicle.all_objects.all()
            self.fields["quotation"].queryset = Quotation.all_objects.all()


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
        company = get_current_company()
        if company is not None:
            self.fields["customer"].queryset = Customer.objects.filter(company=company)
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                company=company,
                stock__status__in=[StockStatus.AVAILABLE, StockStatus.RESERVED],
            ).select_related("stock")
            self.fields["reservation"].queryset = Reservation.objects.filter(
                company=company,
                status="active",
            ).select_related("customer", "vehicle")
        else:
            self.fields["customer"].queryset = Customer.all_objects.all()
            self.fields["vehicle"].queryset = Vehicle.all_objects.all()
            self.fields["reservation"].queryset = Reservation.all_objects.all()

    def clean(self):
        cleaned = super().clean()
        customer = cleaned.get("customer")
        vehicle = cleaned.get("vehicle")
        reservation = cleaned.get("reservation")
        currency = cleaned.get("currency")
        if reservation:
            if customer and reservation.customer_id != customer.pk:
                self.add_error("customer", _("Sale customer must match the reservation customer."))
            if vehicle and reservation.vehicle_id != vehicle.pk:
                self.add_error("vehicle", _("Sale vehicle must match the reserved vehicle."))
            if currency and reservation.currency != currency:
                self.add_error("currency", _("Sale currency must match the reservation currency."))
        elif vehicle:
            stock = getattr(vehicle, "stock", None)
            if stock is None or stock.status != StockStatus.AVAILABLE:
                self.add_error(
                    "vehicle",
                    _("A direct sale requires an available vehicle; select its active reservation otherwise."),
                )
        return cleaned
