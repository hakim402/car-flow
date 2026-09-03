from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission

from .forms import FinancialAccountForm, PaymentForm, SupplierPaymentForm
from .models import FinancialAccount, LedgerEntry
from .services import record_payment, record_supplier_payment, reverse_entry


@require_permission("payments.view")
def entry_list(request):
    entries = LedgerEntry.objects.all()  # TenantManager filters by company.
    return render(request, "payments/list.html", {"entries": entries})


@require_permission("payments.view")
def account_list(request):
    accounts = FinancialAccount.objects.all().select_related("branch")
    return render(request, "payments/account_list.html", {"accounts": accounts})


@require_permission("payments.add")
def account_create(request):
    if request.user.company is None:
        raise PermissionDenied
    form = FinancialAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = form.save(commit=False)
        account.company = request.user.company
        account.save()
        messages.success(request, _("Financial account created."))
        return redirect("payments:account_list")
    return render(
        request,
        "payments/form.html",
        {"form": form, "title": _("Add financial account"), "cancel_url": reverse("payments:account_list")},
    )


@require_permission("payments.add")
def payment_create(request):
    from apps.sales.models import Sale

    sale = None
    sale_pk = request.GET.get("sale") or request.POST.get("sale")
    if sale_pk:
        sale = get_object_or_404(Sale, pk=sale_pk)
    form = PaymentForm(request.POST or None, initial={"sale": sale} if sale else None)
    if request.method == "POST" and form.is_valid():
        sale = form.cleaned_data["sale"]
        try:
            entry = record_payment(
                sale,
                form.cleaned_data["amount"],
                form.cleaned_data["currency"],
                user=request.user,
                description=form.cleaned_data["description"],
                account=form.cleaned_data["account"],
                payment_method=form.cleaned_data["payment_method"],
                transaction_date=form.cleaned_data["transaction_date"],
                reference=form.cleaned_data["reference"],
                receipt_number=form.cleaned_data["receipt_number"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return render(request, "payments/form.html", {"form": form, "title": _("Record payment")})
        messages.success(request, _("Payment recorded."))
        return redirect("payments:receipt", pk=entry.pk)
    return render(request, "payments/form.html", {"form": form, "title": _("Record payment")})


@require_permission("payments.add")
def supplier_payment_create(request):
    """Money paid OUT to a supplier — landed on the supplier detail page
    afterwards so the history reads top-to-bottom."""
    from apps.suppliers.models import Supplier

    supplier = None
    supplier_pk = request.GET.get("supplier") or request.POST.get("supplier")
    if supplier_pk:
        # TenantManager scopes the lookup — another company's supplier 404s.
        supplier = get_object_or_404(Supplier, pk=supplier_pk)
    initial = {"supplier": supplier} if supplier else {}
    form = SupplierPaymentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        supplier = form.cleaned_data["supplier"]
        try:
            record_supplier_payment(
                supplier,
                form.cleaned_data["amount"],
                form.cleaned_data["currency"],
                user=request.user,
                description=form.cleaned_data["description"],
                account=form.cleaned_data["account"],
                payment_method=form.cleaned_data["payment_method"],
                transaction_date=form.cleaned_data["transaction_date"],
                reference=form.cleaned_data["reference"],
                receipt_number=form.cleaned_data["receipt_number"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return render(
                request,
                "payments/form.html",
                {"form": form, "title": _("Pay supplier"), "cancel_url": supplier.get_absolute_url()},
            )
        messages.success(request, _("Payment to supplier recorded."))
        return redirect(supplier)
    return render(
        request,
        "payments/form.html",
        {
            "form": form,
            "title": _("Pay supplier"),
            "cancel_url": supplier.get_absolute_url() if supplier else None,
        },
    )


@require_permission("payments.add")
@require_POST
def entry_reverse(request, pk):
    entry = get_object_or_404(LedgerEntry, pk=pk)
    reverse_entry(entry, user=request.user)
    messages.success(request, _("Entry reversed with a new row."))
    return redirect("payments:list")


@require_permission("payments.view")
def entry_receipt(request, pk):
    entry = get_object_or_404(
        LedgerEntry.objects.select_related("customer", "sale", "account", "created_by"), pk=pk
    )
    allocation = entry.installment_allocations.select_related(
        "installment__agreement"
    ).first()
    agreement = allocation.installment.agreement if allocation else None
    return render(
        request,
        "payments/receipt.html",
        {"entry": entry, "agreement": agreement},
    )
