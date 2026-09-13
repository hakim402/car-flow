from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.utils import timezone

from apps.core.decorators import require_permission
from apps.core.pagination import pagination_context
from apps.payments.models import LedgerEntry
from apps.sales.models import Sale

from .forms import (
    AgreementActionForm,
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
    queryset = FinanceAgreement.objects.select_related(
        "sale", "sale__customer", "sale__vehicle", "partner", "branch"
    ).prefetch_related("installments", "installments__allocations", "installments__allocations__entry")
    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(number__icontains=q)
            | Q(sale__customer__full_name__icontains=q)
            | Q(sale__customer__phone__icontains=q)
            | Q(sale__vehicle__vin__icontains=q)
            | Q(sale__vehicle__make__icontains=q)
            | Q(sale__vehicle__model__icontains=q)
            | Q(partner__name__icontains=q)
        )
    status = request.GET.get("status", "")
    if status in AgreementStatus.values:
        queryset = queryset.filter(status=status)
    agreement_type = request.GET.get("type", "")
    if agreement_type in AgreementType.values:
        queryset = queryset.filter(agreement_type=agreement_type)
    partner = request.GET.get("partner", "")
    if partner.isdigit():
        queryset = queryset.filter(partner_id=partner)
    branch = request.GET.get("branch", "")
    if branch.isdigit():
        queryset = queryset.filter(branch_id=branch)
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
    metrics = {
        "total": len(agreements),
        "active": sum(item.status == AgreementStatus.ACTIVE for item in agreements),
        "overdue": sum(item.summary["overdue"] > 0 for item in agreements),
        "defaulted": sum(item.status == AgreementStatus.DEFAULTED for item in agreements),
        "completed": sum(item.status == AgreementStatus.COMPLETED for item in agreements),
    }
    page = pagination_context(request, agreements, page_size=15)
    company = request.user.company
    return render(
        request,
        "financing/list.html",
        {
            **page,
            "agreements": page["page_obj"],
            "statuses": AgreementStatus.choices,
            "selected_status": status,
            "totals": totals,
            "aging": aging,
            "agreement_types": AgreementType.choices,
            "partners": FinancingPartner.objects.all(),
            "branches": company.branches.all() if company else [],
            "filters": request.GET,
            "metrics": metrics,
            "can_add": request.user.has_permission("financing.add"),
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
    return _agreement_form(request, initial=initial)


@require_permission("financing.change")
def agreement_edit(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    if agreement.status not in {AgreementStatus.DRAFT, AgreementStatus.PENDING_APPROVAL}:
        messages.error(request, _("Only draft or pending agreements can be edited."))
        return redirect(agreement)
    return _agreement_form(request, agreement=agreement)


def _agreement_form(request, agreement=None, initial=None):
    if request.user.company is None:
        raise PermissionDenied
    form = FinanceAgreementForm(request.POST or None, instance=agreement, initial=initial)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.company = request.user.company
        try:
            if agreement:
                record.full_clean()
                record.save()
            else:
                initialize_agreement(record, request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                _("Financing agreement updated.") if agreement else _("Financing agreement created as a draft."),
            )
            return redirect(record)
    return render(
        request,
        "financing/form.html",
        {
            "form": form,
            "agreement": agreement,
            "title": _("Edit financing agreement") if agreement else _("New financing agreement"),
        },
    )


@require_permission("financing.view")
def agreement_detail(request, pk):
    agreement = get_object_or_404(
        FinanceAgreement.objects.select_related("sale", "sale__customer", "sale__vehicle", "partner", "branch")
        .prefetch_related(
            "events", "guarantors", "documents", "installments",
            "installments__allocations", "installments__allocations__entry",
        ),
        pk=pk,
    )
    summary = agreement_summary(agreement)
    preview = schedule_preview(agreement) if agreement.status in {
        AgreementStatus.DRAFT,
        AgreementStatus.PENDING_APPROVAL,
    } else []
    payment_relation = Q(sale=agreement.sale)
    if agreement.sale.reservation_id:
        payment_relation |= Q(reservation_id=agreement.sale.reservation_id)
    return render(
        request,
        "financing/detail.html",
        {
            "agreement": agreement,
            "summary": summary,
            "preview": preview,
            "can_change": request.user.has_permission("financing.change"),
            "payment_entries": LedgerEntry.objects.filter(payment_relation)
            .select_related("account", "created_by")
            .order_by("-transaction_date", "-created_at"),
        },
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
def agreement_default(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    if (
        agreement.agreement_type != AgreementType.DEALER_INSTALLMENT
        or agreement.status != AgreementStatus.ACTIVE
        or agreement_summary(agreement)["overdue"] <= 0
    ):
        messages.error(request, _("Only active agreements with overdue installments can be marked defaulted."))
        return redirect(agreement)
    return _agreement_action(
        request,
        agreement,
        action=mark_defaulted,
        title=_("Mark agreement as defaulted"),
        warning=_("This keeps the debt open and records a permanent default event."),
        success=_("Agreement marked as defaulted."),
        submit_label=_("Mark defaulted"),
    )


@require_permission("financing.change")
def agreement_cancel(request, pk):
    agreement = get_object_or_404(FinanceAgreement, pk=pk)
    if agreement.status not in {AgreementStatus.DRAFT, AgreementStatus.PENDING_APPROVAL}:
        messages.error(request, _("Only draft or pending agreements can be cancelled."))
        return redirect(agreement)
    return _agreement_action(
        request,
        agreement,
        action=cancel_agreement,
        title=_("Cancel financing agreement"),
        warning=_("The agreement will close without creating or changing any cash transaction."),
        success=_("Agreement cancelled."),
        submit_label=_("Cancel agreement"),
    )


def _agreement_action(request, agreement, *, action, title, warning, success, submit_label):
    form = AgreementActionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            action(agreement, request.user, form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, success)
            return redirect(agreement)
    return render(
        request,
        "financing/action_confirm.html",
        {
            "agreement": agreement,
            "form": form,
            "title": title,
            "warning": warning,
            "submit_label": submit_label,
        },
    )


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
    partners = FinancingPartner.objects.prefetch_related("agreements")
    q = request.GET.get("q", "").strip()
    if q:
        partners = partners.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    active = request.GET.get("active", "")
    if active in {"yes", "no"}:
        partners = partners.filter(active=active == "yes")
    rows = list(partners)
    for partner in rows:
        agreements = list(partner.agreements.all())
        partner.agreement_count = len(agreements)
        partner.active_agreement_count = sum(
            item.status == AgreementStatus.ACTIVE for item in agreements
        )
    page = pagination_context(request, rows, page_size=15)
    return render(
        request,
        "financing/partner_list.html",
        {
            **page,
            "partners": page["page_obj"],
            "filters": request.GET,
            "can_manage": request.user.has_permission("financing.add"),
        },
    )


@require_permission("financing.add")
def partner_create(request):
    return _partner_form(request)


@require_permission("financing.view")
def partner_detail(request, pk):
    partner = get_object_or_404(FinancingPartner, pk=pk)
    agreements = partner.agreements.select_related("sale__customer", "sale__vehicle")
    agreement_count = agreements.count()
    active_agreement_count = agreements.filter(status=AgreementStatus.ACTIVE).count()
    completed_agreement_count = agreements.filter(status=AgreementStatus.COMPLETED).count()
    page = pagination_context(request, agreements, page_size=15)
    return render(
        request,
        "financing/partner_detail.html",
        {
            **page,
            "partner": partner,
            "agreements": page["page_obj"],
            "agreement_count": agreement_count,
            "active_agreement_count": active_agreement_count,
            "completed_agreement_count": completed_agreement_count,
            "can_manage": request.user.has_permission("financing.add"),
        },
    )


@require_permission("financing.add")
def partner_edit(request, pk):
    partner = get_object_or_404(FinancingPartner, pk=pk)
    return _partner_form(request, partner)


def _partner_form(request, partner=None):
    if request.user.company is None:
        raise PermissionDenied
    form = FinancingPartnerForm(request.POST or None, instance=partner)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.company = request.user.company
        record.full_clean()
        record.save()
        messages.success(
            request,
            _("Financing partner updated.") if partner else _("Financing partner created."),
        )
        return redirect("financing:partner_detail", pk=record.pk)
    return render(
        request,
        "financing/form.html",
        {
            "form": form,
            "title": _("Edit financing partner") if partner else _("New financing partner"),
            "cancel_url": partner.get_absolute_url() if partner else None,
        },
    )
