from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.constants import CURRENCIES, DEFAULT_CURRENCY
from apps.core.forms import StyledFormMixin
from apps.sales.models import Sale


class PaymentForm(StyledFormMixin, forms.Form):
    sale = forms.ModelChoiceField(label=_("sale"), queryset=Sale.objects.all())
    amount = forms.DecimalField(label=_("amount"), max_digits=14, decimal_places=2, min_value=0)
    currency = forms.ChoiceField(label=_("currency"), choices=CURRENCIES, initial=DEFAULT_CURRENCY)
    description = forms.CharField(label=_("description"), max_length=255, required=False)
