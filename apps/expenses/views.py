from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.decorators import require_permission
from apps.payments.models import EntryType, LedgerEntry

from .forms import ExpenseForm
from .services import record_expense


@require_permission("expenses.view")
def expense_list(request):
    expenses = LedgerEntry.objects.filter(type=EntryType.EXPENSE)
    return render(request, "expenses/list.html", {"expenses": expenses})


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
        )
        messages.success(request, _("Expense recorded."))
        return redirect("expenses:list")
    return render(request, "expenses/form.html", {"form": form, "title": _("Record expense")})
