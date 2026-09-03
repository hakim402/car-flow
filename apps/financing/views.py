from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.utils import timezone

from apps.core.decorators import require_permission
from apps.sales.models import Sale

from .forms import (
    AgreementGuarantorForm,
    FinanceAgreementForm,
    FinancingPartnerForm,
    InstallmentPaymentForm,
)
from .models import AgreementStatus, AgreementType, FinanceAgreement, FinancingPartner
from .services import (
    agreement_summary,
    approve_agreement,
    cancel_agreement,
    initialize_agreement,
    mark_defaulted,
    record_installment_payment,
    record_lender_disbursement,
    schedule_preview,
    submit_agreement,
)


@require_permission("financing.view")
def agreement_list(request):
    queryset = FinanceAgreement.objects.select_related("sale", "sale__customer", "sale__vehicle")
    status = request.GET.get("status", "")
    if status in AgreementStatus.values:
        queryset = queryset.filter(status=status)
    agreements = []
    totals = {}
    aging = {}
    for agreement in queryset:
        summary = agreement_summary(agreement)
        agreement.summary = summary
        agreements.append(agreement)
        if (
            agreement.agreement_type == AgreementType.DEALER_INSTALLMENT
            and agreement.status in {AgreementStatus.ACTIVE, AgreementStatus.DEFAULTED}
        ):
            currency_totals = totals.setdefault(
                agreement.currency, {"outstanding": 0, "overdue": 0}
            )
            currency_totals["outstanding"] += summary["outstanding"]
            currency_totals["overdue"] += summary["overdue"]
            buckets = aging.setdefault(
                agreement.currency,
                {"current": 0, "days_1_30": 0, "days_31_60": 0, "days_61_90": 0, "days_90_plus": 0},
            )
            for _, item in summary["rows"]:
                amount = item["outstanding"]
                if amount <= 0:
                    continue
                days = item["days_overdue"]
                if days <= 0:
                    buckets["current"] += amount
                elif days <= 30:
                    buckets["days_1_30"] += amount
                elif days <= 60:
                    buckets["days_31_60"] += amount
                elif days <= 90:
                    buckets["days_61_90"] += amount
                else:
                    buckets["days_90_plus"] += amount
    return render(
        request,
        "financing/list.html",
        {
            "agreements": agreements,
            "statuses": AgreementStatus.choices,
            "selected_status": status,
            "totals": totals,
            "aging": aging,
        },
    )


@require_permission("financing.add")
def agreement_create(request):
    if request.user.company is None:
        raise PermissionDenied
    initial = {}
    sale_id = request.GET.get("sale")
    if sale_id:
        sale = get_object_or_404(Sale, pk=sale_id)
        initial.update(
            {
                "sale": sale,
                "currency": sale.currency,
                "cash_price": sale.agreed_amount,
                "markup_amount": 0,
                "first_due_date": timezone.localdate() + timedelta(days=30),
            }
        )
    form = FinanceAgreementForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        agreement = form.save(commit=False)
        agreement.company = request.user.company
        try:
            initialize_agreement(agreement, request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Financing agreement created as a draft."))
            return redirect(agreement)
    return render(request, "financing/form.html", {"form": form, "title": _("New financing agreement")})


@require_permission("financing.view")
def agreement_detail(request, pk):
    agreement = get_object_or_404(
        FinanceAgreement.objects.select_related("sale", "sale__customer", "sale__vehicle", "partner"),
        pk=pk,
    )
    summary = agreement_summary(agreement)
    preview = schedule_preview(agreement) if agreement.status in {
        AgreementStatus.DRAFT,
        AgreementStatus.PENDING_APPROVAL,
    } else []
    return render(
        request,
        "financing/detail.html",
        {"agreement": agreement, "summary": summary, "preview": preview},
    )


@require_permission("financing.change")
@require_POST
def agreement_submit(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    try:
        submit_agreement(agreement, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, _("Agreement submitted for approval."))
    return redirect(agreement)


@require_permission("financing.approve")
@require_POST
def agreement_approve(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    try:
        approve_agreement(agreement, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, _("Agreement approved and installment schedule activated."))
    return redirect(agreement)


@require_permission("financing.collect")
def payment_create(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    form = InstallmentPaymentForm(request.POST or None, agreement=agreement)
    if request.method == "POST" and form.is_valid():
        try:
            entry = record_installment_payment(
                agreement,
                form.cleaned_data["amount"],
                form.cleaned_data["account"],
                user=request.user,
                payment_method=form.cleaned_data["payment_method"],
                transaction_date=form.cleaned_data["transaction_date"],
                reference=form.cleaned_data["reference"],
                description=form.cleaned_data["description"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                _("Installment payment recorded. Receipt: %(receipt)s")
                % {"receipt": entry.receipt_number},
            )
            return redirect("payments:receipt", pk=entry.pk)
    return render(
        request,
        "financing/payment_form.html",
        {"form": form, "agreement": agreement, "summary": agreement_summary(agreement)},
    )


@require_permission("financing.collect")
def lender_disbursement_create(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    form = InstallmentPaymentForm(request.POST or None, agreement=agreement)
    if request.method == "POST" and form.is_valid():
        try:
            entry = record_lender_disbursement(
                agreement,
                form.cleaned_data["amount"],
                form.cleaned_data["account"],
                user=request.user,
                payment_method=form.cleaned_data["payment_method"],
                transaction_date=form.cleaned_data["transaction_date"],
                reference=form.cleaned_data["reference"],
                description=form.cleaned_data["description"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Lender disbursement recorded."))
            return redirect("payments:receipt", pk=entry.pk)
    return render(
        request,
        "financing/payment_form.html",
        {
            "form": form,
            "agreement": agreement,
            "summary": agreement_summary(agreement),
            "lender_disbursement": True,
        },
    )


@require_permission("financing.default")
@require_POST
def agreement_default(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    try:
        mark_defaulted(agreement, request.user, request.POST.get("description", ""))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, _("Agreement marked as defaulted."))
    return redirect(agreement)


@require_permission("financing.change")
@require_POST
def agreement_cancel(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    try:
        cancel_agreement(agreement, request.user, request.POST.get("description", ""))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, _("Agreement cancelled."))
    return redirect(agreement)


@require_permission("financing.change")
def guarantor_create(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    if agreement.status not in {AgreementStatus.DRAFT, AgreementStatus.PENDING_APPROVAL}:
        messages.error(request, _("Guarantors can only be added before agreement activation."))
        return redirect(agreement)
    form = AgreementGuarantorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        guarantor = form.save(commit=False)
        guarantor.company = agreement.company
        guarantor.agreement = agreement
        guarantor.full_clean()
        guarantor.save()
        messages.success(request, _("Guarantor added."))
        return redirect(agreement)
    return render(
        request,
        "financing/guarantor_form.html",
        {"form": form, "agreement": agreement},
    )


@require_permission("financing.view")
def partner_list(request):
    return render(
        request,
        "financing/partner_list.html",
        {"partners": FinancingPartner.objects.all()},
    )


@require_permission("financing.add")
def partner_create(request):
    if request.user.company is None:
        raise PermissionDenied
    form = FinancingPartnerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        partner = form.save(commit=False)
        partner.company = request.user.company
        partner.full_clean()
        partner.save()
        messages.success(request, _("Financing partner created."))
        return redirect("financing:partner_list")
    return render(
        request,
        "financing/form.html",
        {"form": form, "title": _("New financing partner")},
    )
