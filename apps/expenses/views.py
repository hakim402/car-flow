from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.decorators import require_permission
from apps.core.pagination import pagination_context
from apps.payments.forms import ReversalForm
from apps.payments.models import EntryType, FinancialAccount, LedgerEntry
from apps.payments.services import reverse_entry

from .forms import ExpenseCategoryForm, ExpenseForm
from .models import ExpenseCategory
from .services import record_expense


@require_permission("expenses.view")
def expense_list(request):
    expenses = LedgerEntry.objects.filter(type=EntryType.EXPENSE).select_related(
        "expense_category", "account", "branch", "created_by", "reversal_of"
    ).prefetch_related("reversals")
    q = request.GET.get("q", "").strip()
    if q:
        expenses = expenses.filter(
            Q(description__icontains=q)
            | Q(vendor__icontains=q)
            | Q(reference__icontains=q)
            | Q(receipt_number__icontains=q)
        )
    category = request.GET.get("category", "")
    if category.isdigit():
        expenses = expenses.filter(expense_category_id=category)
    account = request.GET.get("account", "")
    if account.isdigit():
        expenses = expenses.filter(account_id=account)
    currency = request.GET.get("currency", "")
    if currency:
        expenses = expenses.filter(currency=currency)
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    if date_from:
        expenses = expenses.filter(transaction_date__gte=date_from)
    if date_to:
        expenses = expenses.filter(transaction_date__lte=date_to)
    expense_rows = list(expenses)
    totals = {}
    for expense in expense_rows:
        effect = -expense.amount if expense.reversal_of_id else expense.amount
        totals[expense.currency] = totals.get(expense.currency, Decimal("0")) + effect
    page = pagination_context(request, expense_rows, page_size=20)
    return render(
        request,
        "expenses/list.html",
        {
            **page,
            "expenses": page["page_obj"],
            "totals": totals,
            "categories": ExpenseCategory.objects.all(),
            "accounts": FinancialAccount.objects.all(),
            "filters": request.GET,
            "can_add": request.user.has_permission("expenses.add"),
            "can_reverse": request.user.has_permission("expenses.reverse"),
        },
    )


@require_permission("expenses.view")
def expense_detail(request, pk):
    expense = get_object_or_404(
        LedgerEntry.objects.select_related(
            "expense_category", "account", "branch", "created_by", "reversal_of"
        ).prefetch_related("reversals"),
        pk=pk,
        type=EntryType.EXPENSE,
    )
    return render(
        request,
        "expenses/detail.html",
        {
            "expense": expense,
            "can_reverse": request.user.has_permission("expenses.reverse"),
        },
    )


@require_permission("expenses.view")
def category_list(request):
    categories = ExpenseCategory.objects.annotate(
        transaction_count=Count("ledger_entries"),
    ).order_by("name")
    q = request.GET.get("q", "").strip()
    if q:
        categories = categories.filter(Q(name__icontains=q) | Q(code__icontains=q))
    active = request.GET.get("active", "")
    if active in {"yes", "no"}:
        categories = categories.filter(active=active == "yes")
    page = pagination_context(request, categories, page_size=20)
    return render(
        request,
        "expenses/category_list.html",
        {
            **page,
            "categories": page["page_obj"],
            "filters": request.GET,
            "can_manage": request.user.has_permission("expenses.manage_categories"),
        },
    )


@require_permission("expenses.manage_categories")
def category_create(request):
    return _category_form(request)


@require_permission("expenses.manage_categories")
def category_edit(request, pk):
    category = get_object_or_404(ExpenseCategory, pk=pk)
    return _category_form(request, category)


def _category_form(request, category=None):
    if request.user.company is None:
        raise PermissionDenied
    form = ExpenseCategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.company = request.user.company
        record.save()
        messages.success(
            request,
            _("Expense category updated.") if category else _("Expense category created."),
        )
        return redirect("expenses:category_list")
    return render(
        request,
        "expenses/form.html",
        {
            "form": form,
            "title": _("Edit expense category") if category else _("Add expense category"),
            "eyebrow": _("Expense setup"),
            "submit_label": _("Save category"),
            "cancel_url": reverse("expenses:category_list"),
        },
    )


@require_permission("expenses.add")
def expense_create(request):
    if request.user.company is None:
        raise PermissionDenied
    form = ExpenseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            expense = record_expense(
                request.user.company,
                form.cleaned_data["amount"],
                form.cleaned_data["currency"],
                description=form.cleaned_data["description"],
                user=request.user,
                category=form.cleaned_data.get("category"),
                account=form.cleaned_data.get("account"),
                branch=form.cleaned_data.get("branch"),
                vendor=form.cleaned_data.get("vendor", ""),
                reference=form.cleaned_data.get("reference", ""),
                transaction_date=form.cleaned_data.get("transaction_date"),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Expense recorded."))
            return redirect("expenses:detail", pk=expense.pk)
    return render(
        request,
        "expenses/form.html",
        {
            "form": form,
            "title": _("Record operating expense"),
            "eyebrow": _("Money out"),
            "submit_label": _("Record expense"),
            "cancel_url": reverse("expenses:list"),
        },
    )


@require_permission("expenses.reverse")
def expense_reverse(request, pk):
    expense = get_object_or_404(LedgerEntry, pk=pk, type=EntryType.EXPENSE)
    if expense.reversal_of_id or expense.reversals.exists():
        messages.error(request, _("This expense cannot be reversed."))
        return redirect("expenses:detail", pk=expense.pk)
    form = ReversalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            reversal = reverse_entry(expense, user=request.user, description=form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Expense reversed with a new immutable entry."))
            return redirect("expenses:detail", pk=reversal.pk)
    return render(
        request,
        "payments/reverse_confirm.html",
        {"entry": expense, "form": form, "expense_mode": True},
    )
