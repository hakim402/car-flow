from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.forms import StyledFormMixin
from apps.sales.models import Sale
from apps.suppliers.models import Supplier


class PaymentForm(StyledFormMixin, forms.Form):
    sale = forms.ModelChoiceField(label=_("sale"), queryset=Sale.all_objects.none())
    amount = forms.DecimalField(
        label=_("amount"), max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    currency = forms.ChoiceField(label=_("currency"), choices=CURRENCIES, initial=DEFAULT_CURRENCY)
    description = forms.CharField(label=_("description"), max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Fail-closed tenancy: the tenant manager must only run with a
        # tenant context, which exists at instance time — never at import.
        self.fields["sale"].queryset = Sale.objects.all()


class SupplierPaymentForm(StyledFormMixin, forms.Form):
    supplier = forms.ModelChoiceField(label=_("supplier"), queryset=Supplier.all_objects.none())
    amount = forms.DecimalField(
        label=_("amount"), max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    currency = forms.ChoiceField(label=_("currency"), choices=CURRENCIES, initial="USD")
    description = forms.CharField(label=_("description"), max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same fail-closed rationale as PaymentForm above.
        self.fields["supplier"].queryset = Supplier.objects.all()
