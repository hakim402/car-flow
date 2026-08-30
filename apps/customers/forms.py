from django import forms

from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company

from .models import Customer


class CustomerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["full_name", "phone", "email", "national_id", "branch", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is not None:
            self.fields["branch"].queryset = company.branches.all()
        else:
            self.fields["branch"].queryset = Customer.all_objects.none()
