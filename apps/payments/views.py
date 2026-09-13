from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.accounting.services import _net_totals
from apps.core.constants import CURRENCIES
from apps.core.decorators import require_permission
from apps.core.pagination import pagination_context

from .forms import FinancialAccountForm, PaymentForm, ReversalForm, SupplierPaymentForm
from .models import ENTRY_DIRECTION, EntryType, FinancialAccount, LedgerEntry
from .services import record_payment, record_reservation_payment, record_supplier_payment, reverse_entry


IN_TYPES = {key for key, value in ENTRY_DIRECTION.items() if value == "in"}
OUT_TYPES = {key for key, value in ENTRY_DIRECTION.items() if value == "out"}


def _decorate_entries(entries):
    for entry in entries:
        direction = entry.direction
        if entry.reversal_of_id:
            direction = "out" if direction == "in" else "in"
        entry.economic_direction = direction
        entry.economic_sign = "+" if direction == "in" else "−"
        entry.is_reversed = bool(list(entry.reversals.all()))
    return entries


def _entry_queryset(request):
    entries = LedgerEntry.objects.select_related(
        "account", "branch", "customer", "sale", "reservation", "purchase_order",
        "supplier", "expense_category", "created_by", "reversal_of",
    ).prefetch_related("reversals")
    q = request.GET.get("q", "").strip()
    if q:
        entries = entries.filter(
            Q(receipt_number__icontains=q)
            | Q(reference__icontains=q)
            | Q(description__icontains=q)
            | Q(vendor__icontains=q)
            | Q(customer__full_name__icontains=q)
            | Q(supplier__name__icontains=q)
            | Q(purchase_order__reference__icontains=q)
            | Q(account__name__icontains=q)
        )
    entry_type = request.GET.get("type", "")
    if entry_type in EntryType.values:
        entries = entries.filter(type=entry_type)
    direction = request.GET.get("direction", "")
    if direction == "in":
        entries = entries.filter(type__in=IN_TYPES)
    elif direction == "out":
        entries = entries.filter(type__in=OUT_TYPES)
    currency = request.GET.get("currency", "")
    if currency:
        entries = entries.filter(currency=currency)
    account = request.GET.get("account", "")
    if account.isdigit():
        entries = entries.filter(account_id=account)
    branch = request.GET.get("branch", "")
    if branch.isdigit():
        entries = entries.filter(branch_id=branch)
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    if date_from:
        entries = entries.filter(transaction_date__gte=date_from)
    if date_to:
        entries = entries.filter(transaction_date__lte=date_to)
    return entries


@require_permission("payments.view")
def entry_list(request):
    entries = _entry_queryset(request)
    entries_for_totals = list(entries)
    incoming = _net_totals(item for item in entries_for_totals if item.direction == "in")
    outgoing = {
        currency: -amount
        for currency, amount in _net_totals(
            item for item in entries_for_totals if item.direction == "out"
        ).items()
    }
    page = pagination_context(request, entries, page_size=20)
    _decorate_entries(page["page_obj"].object_list)
    company = request.user.company
    return render(
        request,
        "payments/list.html",
        {
            **page,
            "entries": page["page_obj"],
            "incoming": incoming,
            "outgoing": outgoing,
            "reversed_count": entries.filter(reversal_of__isnull=False).count(),
            "entry_types": EntryType.choices,
            "currency_codes": [code for code, _label in CURRENCIES],
            "accounts": FinancialAccount.objects.all(),
            "branches": company.branches.all() if company else [],
            "filters": request.GET,
            "can_add": request.user.has_permission("payments.add"),
            "can_reverse": request.user.has_permission("payments.reverse"),
        },
    )


@require_permission("payments.view")
def entry_detail(request, pk):
    entry = get_object_or_404(
        LedgerEntry.objects.select_related(
            "account", "branch", "customer", "sale", "reservation", "purchase_order",
            "supplier", "expense_category", "created_by", "reversal_of",
        ).prefetch_related("reversals"),
        pk=pk,
    )
    _decorate_entries([entry])
    allocation = entry.installment_allocations.select_related("installment__agreement").first()
    agreement = allocation.installment.agreement if allocation else None
    return render(
        request,
        "payments/detail.html",
        {
            "entry": entry,
            "agreement": agreement,
            "can_reverse": request.user.has_permission("payments.reverse"),
        },
    )


@require_permission("payments.view")
def account_list(request):
    accounts = FinancialAccount.objects.select_related("branch").prefetch_related(
        "ledger_entries", "ledger_entries__reversal_of"
    )
    q = request.GET.get("q", "").strip()
    if q:
        accounts = accounts.filter(Q(name__icontains=q) | Q(branch__name__icontains=q))
    account_type = request.GET.get("type", "")
    if account_type in FinancialAccount.AccountType.values:
        accounts = accounts.filter(account_type=account_type)
    currency = request.GET.get("currency", "")
    if currency:
        accounts = accounts.filter(currency=currency)
    active = request.GET.get("active", "")
    if active in {"yes", "no"}:
        accounts = accounts.filter(active=active == "yes")
    account_rows = list(accounts)
    totals = {}
    for account in account_rows:
        account_entries = list(account.ledger_entries.all())
        account.balance = _net_totals(account_entries).get(account.currency, Decimal("0"))
        account.transaction_count = len(account_entries)
        totals[account.currency] = totals.get(account.currency, Decimal("0")) + account.balance
    page = pagination_context(request, account_rows, page_size=15)
    return render(
        request,
        "payments/account_list.html",
        {
            **page,
            "accounts": page["page_obj"],
            "totals": totals,
            "account_types": FinancialAccount.AccountType.choices,
            "filters": request.GET,
            "can_manage": request.user.has_permission("payments.accounts_manage"),
        },
    )


@require_permission("payments.view")
def account_detail(request, pk):
    account = get_object_or_404(FinancialAccount.objects.select_related("branch"), pk=pk)
    entries = account.ledger_entries.select_related(
        "customer", "supplier", "purchase_order", "sale", "created_by", "reversal_of"
    ).order_by("transaction_date", "created_at", "pk")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    if date_from:
        entries = entries.filter(transaction_date__gte=date_from)
    if date_to:
        entries = entries.filter(transaction_date__lte=date_to)
    running = Decimal("0")
    statement = []
    for entry in entries:
        _decorate_entries([entry])
        running += entry.amount if entry.economic_direction == "in" else -entry.amount
        entry.running_balance = running
        statement.append(entry)
    statement.reverse()
    page = pagination_context(request, statement, page_size=25)
    return render(
        request,
        "payments/account_detail.html",
        {
            **page,
            "account": account,
            "entries": page["page_obj"],
            "closing_balance": running,
            "filters": request.GET,
            "can_manage": request.user.has_permission("payments.accounts_manage"),
        },
    )


@require_permission("payments.accounts_manage")
def account_create(request):
    return _account_form(request)


@require_permission("payments.accounts_manage")
def account_edit(request, pk):
    account = get_object_or_404(FinancialAccount, pk=pk)
    return _account_form(request, account)


def _account_form(request, account=None):
    if request.user.company is None:
        raise PermissionDenied
    form = FinancialAccountForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.company = request.user.company
        record.save()
        messages.success(
            request,
            _("Financial account updated.") if account else _("Financial account created."),
        )
        return redirect("payments:account_detail", pk=record.pk)
    return render(
        request,
        "payments/form.html",
        {
            "form": form,
            "title": _("Edit financial account") if account else _("Add financial account"),
            "eyebrow": _("Account setup"),
            "submit_label": _("Save account"),
            "cancel_url": account.get_absolute_url() if account else reverse("payments:account_list"),
        },
    )


@require_permission("payments.add")
def payment_create(request):
    from apps.sales.models import Reservation, Sale

    sale = None
    reservation = None
    sale_pk = request.GET.get("sale") or request.POST.get("sale")
    reservation_pk = request.GET.get("reservation") or request.POST.get("reservation")
    if sale_pk:
        sale = get_object_or_404(Sale, pk=sale_pk)
    if reservation_pk:
        reservation = get_object_or_404(Reservation, pk=reservation_pk)
    target = sale or reservation
    initial = {"sale": sale, "reservation": reservation}
    if target:
        initial["currency"] = target.currency
    form = PaymentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        sale = form.cleaned_data["sale"]
        reservation = form.cleaned_data["reservation"]
        try:
            record = record_payment if sale else record_reservation_payment
            target = sale or reservation
            entry = record(
                target,
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
        else:
            messages.success(request, _("Payment recorded."))
            return redirect("payments:detail", pk=entry.pk)
    return render(
        request,
        "payments/form.html",
        {
            "form": form,
            "title": _("Record customer payment"),
            "eyebrow": _("Money in"),
            "submit_label": _("Record payment"),
            "cancel_url": target.get_absolute_url() if target else reverse("payments:list"),
        },
    )


@require_permission("payments.add")
def supplier_payment_create(request):
    from apps.purchases.models import PurchaseOrder
    from apps.suppliers.models import Supplier

    supplier = None
    purchase_order = None
    supplier_pk = request.GET.get("supplier") or request.POST.get("supplier")
    order_pk = request.GET.get("purchase_order") or request.POST.get("purchase_order")
    if supplier_pk:
        supplier = get_object_or_404(Supplier, pk=supplier_pk)
    if order_pk:
        purchase_order = get_object_or_404(PurchaseOrder.objects.select_related("supplier"), pk=order_pk)
        supplier = purchase_order.supplier
    initial = {"supplier": supplier, "purchase_order": purchase_order}
    if purchase_order:
        currencies = list(purchase_order.total_by_currency())
        if len(currencies) == 1:
            initial["currency"] = currencies[0]
    form = SupplierPaymentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        supplier = form.cleaned_data["supplier"]
        purchase_order = form.cleaned_data["purchase_order"]
        try:
            entry = record_supplier_payment(
                supplier,
                form.cleaned_data["amount"],
                form.cleaned_data["currency"],
                user=request.user,
                purchase_order=purchase_order,
                description=form.cleaned_data["description"],
                account=form.cleaned_data["account"],
                payment_method=form.cleaned_data["payment_method"],
                transaction_date=form.cleaned_data["transaction_date"],
                reference=form.cleaned_data["reference"],
                receipt_number=form.cleaned_data["receipt_number"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Payment to supplier recorded."))
            return redirect("payments:detail", pk=entry.pk)
    return render(
        request,
        "payments/form.html",
        {
            "form": form,
            "title": _("Record supplier payment"),
            "eyebrow": _("Money out"),
            "submit_label": _("Record supplier payment"),
            "cancel_url": purchase_order.get_absolute_url() if purchase_order else (
                supplier.get_absolute_url() if supplier else reverse("payments:list")
            ),
        },
    )


@require_permission("payments.reverse")
def entry_reverse(request, pk):
    entry = get_object_or_404(LedgerEntry.objects.select_related("account", "customer", "supplier"), pk=pk)
    if entry.reversal_of_id or entry.reversals.exists():
        messages.error(request, _("This transaction cannot be reversed."))
        return redirect("payments:detail", pk=entry.pk)
    form = ReversalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            reversal = reverse_entry(entry, user=request.user, description=form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Transaction reversed with a new immutable entry."))
            return redirect("payments:detail", pk=reversal.pk)
    return render(request, "payments/reverse_confirm.html", {"entry": entry, "form": form})


@require_permission("payments.view")
def entry_receipt(request, pk):
    entry = get_object_or_404(
        LedgerEntry.objects.select_related(
            "customer", "supplier", "sale", "purchase_order", "account", "created_by", "reversal_of"
        ),
        pk=pk,
    )
    _decorate_entries([entry])
    allocation = entry.installment_allocations.select_related("installment__agreement").first()
    agreement = allocation.installment.agreement if allocation else None
    return render(request, "payments/receipt.html", {"entry": entry, "agreement": agreement})
