"""Validated, reusable filters for interactive, exported and shared reports."""
from django import forms
from django.utils.translation import gettext_lazy as _

from apps.branches.models import Branch
from apps.core.forms import StyledFormMixin


class ReportFilterForm(StyledFormMixin, forms.Form):
    date_from = forms.DateField(label=_("From date"), required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label=_("To date"), required=False, widget=forms.DateInput(attrs={"type": "date"}))
    branch = forms.ChoiceField(label=_("Branch"), required=False)
    q = forms.CharField(label=_("Search"), required=False, max_length=200)

    def __init__(self, *args, company=None, report_key=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.report_key = report_key
        branches = Branch.objects.filter(company=company) if company else Branch.objects.none()
        self.fields["branch"].choices = [("", _("All branches")), *[(str(branch.pk), branch.name) for branch in branches]]
        if report_key:
            from .reporting import REPORTS
            mode = REPORTS[report_key]["date_mode"]
            if mode != "period":
                for field in ("date_from", "date_to", "as_of"):
                    self.fields.pop(field, None)
            if report_key == "activity":
                self.fields["action"] = forms.ChoiceField(
                    label=_("Action"), required=False,
                    choices=[
                        ("", _("All actions")),
                        ("+", _("Created")),
                        ("~", _("Updated")),
                        ("-", _("Deleted")),
                    ],
                )
                self.fields["module"] = forms.ChoiceField(
                    label=_("Workspace"), required=False,
                    choices=[
                        ("", _("All workspaces")),
                        ("sales", _("Sales")),
                        ("stock", _("Buy and stock")),
                        ("customers", _("Customer records")),
                        ("suppliers", _("Supplier records")),
                    ],
                )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("date_from"), cleaned.get("date_to")
        if start and end and start > end:
            self.add_error("date_to", _("The end date must be on or after the start date."))
        if self.data.get("compare") == "1" and "date_to" in self.fields and not (start and end):
            self.add_error(None, _("Choose both dates to compare periods."))
        return cleaned
