from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import require_permission

from .forms import PaymentForm
from .models import LedgerEntry
from .services import record_payment, reverse_entry


@require_permission("payments.view")
def entry_list(request):
    entries = LedgerEntry.objects.all()  # TenantManager filters by company.
    return render(request, "payments/list.html", {"entries": entries})


@require_permission("payments.add")
def payment_create(request):
    form = PaymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        sale = form.cleaned_data["sale"]
        record_payment(
            sale,
            form.cleaned_data["amount"],
            form.cleaned_data["currency"],
            user=request.user,
            description=form.cleaned_data["description"],
        )
        messages.success(request, _("Payment recorded."))
        return redirect("payments:list")
    return render(request, "payments/form.html", {"form": form, "title": _("Record payment")})


@require_permission("payments.add")
@require_POST
def entry_reverse(request, pk):
    entry = get_object_or_404(LedgerEntry, pk=pk)
    reverse_entry(entry, user=request.user)
    messages.success(request, _("Entry reversed with a new row."))
    return redirect("payments:list")
