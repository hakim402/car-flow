from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company
from apps.payments.models import FinancialAccount, PaymentMethod
from apps.purchases.models import PurchaseOrder, PurchaseStatus
from apps.sales.models import Reservation, ReservationStatus, Sale, SaleStatus
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

    def clean_currency(self):
        currency = self.cleaned_data["currency"]
        if self.instance.pk and self.instance.ledger_entries.exists() and currency != self.instance.currency:
            raise forms.ValidationError(
                _("Currency cannot be changed after transactions have been recorded.")
            )
        return currency


class PaymentForm(StyledFormMixin, forms.Form):
    sale = forms.ModelChoiceField(
        label=_("sale"),
        queryset=Sale.all_objects.none(),
        required=False,
        help_text=_("Completed sale this payment belongs to."),
    )
    reservation = forms.ModelChoiceField(
        label=_("reservation"),
        queryset=Reservation.all_objects.none(),
        required=False,
        help_text=_("Active reservation this deposit belongs to."),
    )
    account = forms.ModelChoiceField(
        label=_("financial account"),
        queryset=FinancialAccount.all_objects.none(),
        required=True,
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
        widget=forms.DateInput(attrs={"type": "date"}),
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
            self.fields["sale"].queryset = Sale.objects.filter(
                status=SaleStatus.COMPLETED
            )
            self.fields["reservation"].queryset = Reservation.objects.filter(
                status=ReservationStatus.ACTIVE
            )
            self.fields["account"].queryset = FinancialAccount.objects.filter(active=True)
        else:
            self.fields["sale"].queryset = Sale.all_objects.none()
            self.fields["reservation"].queryset = Reservation.all_objects.none()
            self.fields["account"].queryset = FinancialAccount.all_objects.none()

    def clean(self):
        cleaned = super().clean()
        sale = cleaned.get("sale")
        reservation = cleaned.get("reservation")
        account = cleaned.get("account")
        currency = cleaned.get("currency")
        if bool(sale) == bool(reservation):
            raise forms.ValidationError(
                _("Select exactly one sale or reservation for this payment.")
            )
        if sale and currency and sale.currency != currency:
            self.add_error("currency", _("Payment currency must match the sale currency."))
        if reservation and currency and reservation.currency != currency:
            self.add_error(
                "currency", _("Payment currency must match the reservation currency.")
            )
        if account and currency and account.currency != currency:
            self.add_error("account", _("Payment currency must match the financial account currency."))
        return cleaned


class SupplierPaymentForm(StyledFormMixin, forms.Form):
    purchase_order = forms.ModelChoiceField(
        label=_("purchase order"),
        queryset=PurchaseOrder.all_objects.none(),
        help_text=_("Purchase order whose outstanding balance this payment reduces."),
    )
    supplier = forms.ModelChoiceField(
        label=_("supplier"),
        queryset=Supplier.all_objects.none(),
        help_text=_("Supplier being paid for this purchase or invoice."),
    )
    account = forms.ModelChoiceField(
        label=_("financial account"),
        queryset=FinancialAccount.all_objects.none(),
        required=True,
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
        widget=forms.DateInput(attrs={"type": "date"}),
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
            self.fields["purchase_order"].queryset = PurchaseOrder.objects.exclude(
                status=PurchaseStatus.CANCELLED
            ).select_related("supplier")
            self.fields["account"].queryset = FinancialAccount.objects.filter(active=True)
        else:
            self.fields["supplier"].queryset = Supplier.all_objects.none()
            self.fields["purchase_order"].queryset = PurchaseOrder.all_objects.none()
            self.fields["account"].queryset = FinancialAccount.all_objects.none()

    def clean(self):
        cleaned = super().clean()
        account = cleaned.get("account")
        supplier = cleaned.get("supplier")
        purchase_order = cleaned.get("purchase_order")
        currency = cleaned.get("currency")
        if supplier and purchase_order and purchase_order.supplier_id != supplier.pk:
            self.add_error(
                "purchase_order", _("Purchase order must belong to the selected supplier.")
            )
        if purchase_order and currency and currency not in purchase_order.total_by_currency():
            self.add_error(
                "currency", _("Payment currency must match a currency used by the purchase order.")
            )
        if account and currency and account.currency != currency:
            self.add_error("account", _("Payment currency must match the financial account currency."))
        return cleaned


class ReversalForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(
        label=_("reversal reason"),
        min_length=5,
        max_length=255,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Explain why this immutable transaction must be reversed."),
    )
