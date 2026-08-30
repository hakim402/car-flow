from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.branches.models import Branch
from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company
from apps.payments.models import FinancialAccount

from .models import ExpenseCategory


class ExpenseCategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name", "code", "active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Operating expenses"}),
            "code": forms.TextInput(attrs={"placeholder": "OE-001"}),
        }


class ExpenseForm(StyledFormMixin, forms.Form):
    transaction_date = forms.DateField(
        label=_("transaction date"),
        help_text=_("Date the expense was incurred or paid."),
    )
    category = forms.ModelChoiceField(
        label=_("category"),
        queryset=ExpenseCategory.all_objects.none(),
        help_text=_("Type of operating expense for reporting and analysis."),
    )
    amount = forms.DecimalField(
        label=_("amount"),
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text=_("Net cash value paid for this expense."),
    )
    currency = forms.ChoiceField(
        label=_("currency"),
        choices=CURRENCIES,
        initial=DEFAULT_CURRENCY,
        help_text=_("Currency used for the expense record."),
    )
    account = forms.ModelChoiceField(
        label=_("financial account"),
        queryset=FinancialAccount.all_objects.none(),
        required=False,
        help_text=_("Cash or bank account from which this expense was paid."),
    )
    branch = forms.ModelChoiceField(
        label=_("branch"),
        queryset=Branch.objects.none(),
        required=False,
        help_text=_("Branch that is responsible for this operating expense."),
    )
    vendor = forms.CharField(
        label=_("vendor / payee"),
        max_length=200,
        required=False,
        help_text=_("Supplier, service provider, or payee name for this expense."),
    )
    reference = forms.CharField(
        label=_("reference"),
        max_length=100,
        required=False,
        help_text=_("Invoice, voucher, or internal reference for the expense."),
    )
    description = forms.CharField(
        label=_("description"),
        max_length=255,
        required=False,
        help_text=_("Brief explanation of the expense and why it was incurred."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is not None:
            self.fields["category"].queryset = ExpenseCategory.objects.all()
            self.fields["account"].queryset = FinancialAccount.objects.all()
            self.fields["branch"].queryset = Branch.objects.filter(company=company)
        else:
            self.fields["category"].queryset = ExpenseCategory.all_objects.none()
            self.fields["account"].queryset = FinancialAccount.all_objects.none()
            self.fields["branch"].queryset = Branch.objects.none()
