from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.core.tenancy import get_current_company
from apps.payments.models import FinancialAccount, PaymentMethod
from apps.sales.models import Sale

from .models import AgreementGuarantor, FinanceAgreement, FinancingPartner


class FinanceAgreementForm(StyledFormMixin, forms.ModelForm):
    sale = forms.ModelChoiceField(
        label=_("sale"), queryset=Sale.all_objects.none(), help_text=_("Vehicle sale financed by this agreement.")
    )
    partner = forms.ModelChoiceField(
        label=_("financing partner"),
        queryset=FinancingPartner.all_objects.none(),
        required=False,
        help_text=_("Required only when an external bank or lender provides the financing."),
    )

    class Meta:
        model = FinanceAgreement
        fields = [
            "sale",
            "branch",
            "agreement_type",
            "partner",
            "external_reference",
            "currency",
            "cash_price",
            "markup_amount",
            "down_payment_required",
            "installment_count",
            "frequency",
            "first_due_date",
            "grace_days",
            "notes",
        ]
        widgets = {
            "first_due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "agreement_type": _(
                "Dealer installments remain a dealership receivable; external lender debt belongs to the lender."
            ),
            "cash_price": _(
                "Base vehicle price before fixed installment markup. Cash price plus markup must equal the sale amount."
            ),
            "markup_amount": _("Fixed disclosed profit added for the deferred sale."),
            "down_payment_required": _(
                "This must be received as a real ledger payment before approval."
            ),
            "installment_count": _(
                "The financed balance is divided across this many payments. Use one installment for a simple remaining customer balance or short-term loan."
            ),
            "grace_days": _("Days after each due date before the installment becomes overdue."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = get_current_company()
        if company is None:
            self.fields["sale"].queryset = Sale.all_objects.none()
            self.fields["partner"].queryset = FinancingPartner.all_objects.none()
            self.fields["branch"].queryset = FinanceAgreement._meta.get_field("branch").remote_field.model.objects.none()
            return
        self.fields["sale"].queryset = Sale.objects.filter(finance_agreement__isnull=True).select_related(
            "customer", "vehicle"
        )
        self.fields["partner"].queryset = FinancingPartner.objects.filter(active=True)
        # Branch currently has no lifecycle flag; the reverse relation is
        # already scoped to the authenticated user's company.
        self.fields["branch"].queryset = company.branches.all()


class InstallmentPaymentForm(StyledFormMixin, forms.Form):
    account = forms.ModelChoiceField(
        label=_("financial account"),
        queryset=FinancialAccount.all_objects.none(),
        help_text=_("Cashbox or bank account receiving this installment."),
    )
    amount = forms.DecimalField(
        label=_("amount"), max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    payment_method = forms.ChoiceField(
        label=_("payment method"), choices=PaymentMethod.choices, initial=PaymentMethod.CASH
    )
    transaction_date = forms.DateField(
        label=_("transaction date"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    reference = forms.CharField(label=_("reference"), max_length=100, required=False)
    description = forms.CharField(
        label=_("description"), max_length=255, required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, agreement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.agreement = agreement
        if agreement is not None:
            self.fields["account"].queryset = FinancialAccount.objects.filter(
                active=True, currency=agreement.currency
            )
        else:
            self.fields["account"].queryset = FinancialAccount.all_objects.none()


class AgreementGuarantorForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = AgreementGuarantor
        fields = ["full_name", "national_id", "phone", "address"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class FinancingPartnerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinancingPartner
        fields = ["name", "partner_type", "phone", "email", "active", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}
