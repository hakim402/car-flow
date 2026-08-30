from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company
from apps.payments.models import FinancialAccount, PaymentMethod
from apps.sales.models import Sale
from apps.suppliers.models import Supplier


class FinancialAccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinancialAccount
        fields = ["name", "branch", "account_type", "currency", "active", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Main cash account"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Purpose, bank details, or account notes"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is not None:
            self.fields["branch"].queryset = company.branches.all()
        else:
            self.fields["branch"].queryset = FinancialAccount._meta.get_field("branch").remote_field.model.objects.none()


class PaymentForm(StyledFormMixin, forms.Form):
    sale = forms.ModelChoiceField(
        label=_("sale"),
        queryset=Sale.all_objects.none(),
        help_text=_("Completed sale this payment belongs to."),
    )
    account = forms.ModelChoiceField(
        label=_("financial account"),
        queryset=FinancialAccount.all_objects.none(),
        required=False,
        help_text=_("Cash or bank account where the payment was received."),
    )
    amount = forms.DecimalField(
        label=_("amount"),
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text=_("Value received in the selected currency."),
    )
    currency = forms.ChoiceField(
        label=_("currency"),
        choices=CURRENCIES,
        initial=DEFAULT_CURRENCY,
        help_text=_("Currency of the payment and the related sale."),
    )
    payment_method = forms.ChoiceField(
        label=_("payment method"),
        choices=PaymentMethod.choices,
        initial=PaymentMethod.CASH,
        help_text=_("How the customer paid the invoice or deposit."),
    )
    transaction_date = forms.DateField(
        label=_("transaction date"),
        required=False,
        help_text=_("Date the money was received."),
    )
    reference = forms.CharField(
        label=_("reference"),
        max_length=100,
        required=False,
        help_text=_("Customer reference, transfer note, or internal reference."),
    )
    receipt_number = forms.CharField(
        label=_("receipt number"),
        max_length=100,
        required=False,
        help_text=_("Stable receipt or payment slip number for customer documents."),
    )
    description = forms.CharField(
        label=_("description"),
        max_length=255,
        required=False,
        help_text=_("Short note explaining the purpose of this payment."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is not None:
            self.fields["sale"].queryset = Sale.objects.all()
            self.fields["account"].queryset = FinancialAccount.objects.all()
        else:
            self.fields["sale"].queryset = Sale.all_objects.none()
            self.fields["account"].queryset = FinancialAccount.all_objects.none()


class SupplierPaymentForm(StyledFormMixin, forms.Form):
    supplier = forms.ModelChoiceField(
        label=_("supplier"),
        queryset=Supplier.all_objects.none(),
        help_text=_("Supplier being paid for this purchase or invoice."),
    )
    account = forms.ModelChoiceField(
        label=_("financial account"),
        queryset=FinancialAccount.all_objects.none(),
        required=False,
        help_text=_("Bank or cash account used to pay the supplier."),
    )
    amount = forms.DecimalField(
        label=_("amount"),
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text=_("Amount released to the supplier in this currency."),
    )
    currency = forms.ChoiceField(
        label=_("currency"),
        choices=CURRENCIES,
        initial="USD",
        help_text=_("Currency used for the supplier payment."),
    )
    payment_method = forms.ChoiceField(
        label=_("payment method"),
        choices=PaymentMethod.choices,
        initial=PaymentMethod.CASH,
        help_text=_("Method used to transfer funds to the supplier."),
    )
    transaction_date = forms.DateField(
        label=_("transaction date"),
        required=False,
        help_text=_("Date the supplier payment was made."),
    )
    reference = forms.CharField(
        label=_("reference"),
        max_length=100,
        required=False,
        help_text=_("Invoice, voucher, or transfer reference for matching."),
    )
    receipt_number = forms.CharField(
        label=_("receipt number"),
        max_length=100,
        required=False,
        help_text=_("Bank or vendor receipt number, when available."),
    )
    description = forms.CharField(
        label=_("description"),
        max_length=255,
        required=False,
        help_text=_("Notes about the supplier invoice or payment purpose."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is not None:
            self.fields["supplier"].queryset = Supplier.objects.all()
            self.fields["account"].queryset = FinancialAccount.objects.all()
        else:
            self.fields["supplier"].queryset = Supplier.all_objects.none()
            self.fields["account"].queryset = FinancialAccount.all_objects.none()
