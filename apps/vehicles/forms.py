from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company

from .models import Vehicle


class VehicleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Vehicle
        # `status` is deliberately absent: inventory state is authoritative on
        # VehicleStock (§8) and mutated only through the inventory services.
        fields = [
            "vin",
            "plate_number",
            "registration_number",
            "engine_number",
            "chassis_number",
            "make",
            "model",
            "model_variant",
            "year",
            "color",
            "mileage",
            "body_type",
            "fuel_type",
            "transmission",
            "drive_type",
            "door_count",
            "seating_capacity",
            "country_of_origin",
            "first_registration_date",
            "branch",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Any special remarks, damage notes, or internal observations..."}),
            "first_registration_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_user = getattr(self, "current_user", None)
        if not self.initial.get("branch") and current_user is not None and getattr(current_user, "branch_id", None):
            self.initial["branch"] = current_user.branch_id

        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect, forms.HiddenInput)):
                continue

            base_classes = [
                "w-full rounded-xl border border-slate-300 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 shadow-sm transition",
                "focus:border-amber-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-amber-100",
            ]
            if field_name == "notes":
                base_classes.append("min-h-[110px]")
            elif field_name in {"branch", "country_of_origin", "body_type", "fuel_type", "transmission", "drive_type"}:
                base_classes.append("max-w-sm")
            else:
                base_classes.append("max-w-md")
            widget.attrs["class"] = " ".join(base_classes)

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
