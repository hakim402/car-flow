from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.decorators import require_permission
from apps.payments.models import EntryType, LedgerEntry

from .forms import ExpenseCategoryForm, ExpenseForm
from .models import ExpenseCategory
from .services import record_expense


@require_permission("expenses.view")
def expense_list(request):
    expenses = LedgerEntry.objects.filter(type=EntryType.EXPENSE)
    return render(request, "expenses/list.html", {"expenses": expenses})


@require_permission("expenses.view")
def category_list(request):
    categories = ExpenseCategory.objects.all().order_by("name")
    return render(request, "expenses/category_list.html", {"categories": categories})


@require_permission("expenses.add")
def category_create(request):
    if request.user.company is None:
        raise PermissionDenied
    form = ExpenseCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        category = form.save(commit=False)
        category.company = request.user.company
        category.save()
        messages.success(request, _("Expense category created."))
        return redirect("expenses:category_list")
    return render(
        request,
        "expenses/form.html",
        {"form": form, "title": _("Add expense category"), "cancel_url": reverse("expenses:category_list")},
    )


@require_permission("expenses.add")
def expense_create(request):
    if request.user.company is None:
        raise PermissionDenied
    form = ExpenseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        record_expense(
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
        messages.success(request, _("Expense recorded."))
        return redirect("expenses:list")
    return render(request, "expenses/form.html", {"form": form, "title": _("Record expense")})
