from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company

from .models import Vehicle


class VehicleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ["vin", "make", "model", "year", "color", "mileage", "status", "branch", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is not None:
            # Branch choices limited to the current tenant — never trust the client.
            self.fields["branch"].queryset = company.branches.all()

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get("branch")
        company = get_current_company()
        if branch is not None and company is not None and branch.company_id != company.pk:
            raise forms.ValidationError({"branch": _("Branch does not belong to your company.")})
        return cleaned
