from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.core.models import ImmutableRecordError
from apps.core.tenancy import company_scope
from apps.core.testing import SaleFactory, UserFactory
from apps.payments.models import FinancialAccount
from apps.payments.services import record_payment, reverse_entry
from apps.sales.models import SaleStatus

from apps.financing.models import (
    AgreementStatus,
    AgreementType,
    FinanceAgreement,
    FinancingPartner,
)
from apps.financing.services import (
    agreement_summary,
    approve_agreement,
    initialize_agreement,
    record_installment_payment,
    record_lender_disbursement,
    schedule_preview,
    submit_agreement,
)


@pytest.mark.django_db
def test_finance_agreement_create_page_renders(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("financing:create"))

    assert response.status_code == 200


def _agreement(sale, user, **overrides):
    values = {
        "company": sale.company,
        "sale": sale,
        "currency": sale.currency,
        "cash_price": sale.agreed_amount,
        "markup_amount": Decimal("0"),
        "down_payment_required": Decimal("0"),
        "installment_count": 3,
        "frequency": "monthly",
        "first_due_date": date.today() + timedelta(days=30),
    }
    values.update(overrides)
    return initialize_agreement(FinanceAgreement(**values), user)


@pytest.mark.django_db
def test_schedule_rounding_puts_remainder_on_final_installment():
    sale = SaleFactory(agreed_amount=Decimal("100.00"), currency="AFN")
    user = UserFactory(company=sale.company)
    with company_scope(sale.company):
        agreement = _agreement(sale, user)
        rows = schedule_preview(agreement)
    assert [row["amount"] for row in rows] == [
        Decimal("33.33"), Decimal("33.33"), Decimal("33.34")
    ]
    assert sum(row["amount"] for row in rows) == Decimal("100.00")


@pytest.mark.django_db
def test_activation_requires_completed_sale_and_down_payment():
    sale = SaleFactory(agreed_amount=Decimal("1200.00"), currency="AFN")
    user = UserFactory(company=sale.company)
    with company_scope(sale.company):
        agreement = _agreement(
            sale, user, down_payment_required=Decimal("200.00"), installment_count=10
        )
        submit_agreement(agreement, user)
        with pytest.raises(ValidationError, match="Complete the vehicle sale"):
            approve_agreement(agreement, user)
        sale.status = SaleStatus.COMPLETED
        sale.save(update_fields=["status", "updated_at"])
        with pytest.raises(ValidationError, match="required down payment"):
            approve_agreement(agreement, user)
        record_payment(sale, Decimal("200.00"), "AFN", user=user)
        agreement = approve_agreement(agreement, user)
        assert agreement.status == AgreementStatus.ACTIVE
        assert agreement.installments.count() == 10
        assert sum(agreement.installments.values_list("amount", flat=True)) == Decimal("1000.00")


@pytest.mark.django_db
def test_partial_payment_allocates_oldest_first_and_reversal_reopens_schedule():
    sale = SaleFactory(
        agreed_amount=Decimal("1200.00"), currency="AFN", status=SaleStatus.COMPLETED
    )
    user = UserFactory(company=sale.company)
    with company_scope(sale.company):
        account = FinancialAccount.objects.create(
            company=sale.company, name="AFN Cashbox", currency="AFN", active=True
        )
        agreement = _agreement(
            sale,
            user,
            down_payment_required=Decimal("200.00"),
            installment_count=10,
        )
        record_payment(sale, Decimal("200.00"), "AFN", user=user, account=account)
        submit_agreement(agreement, user)
        agreement = approve_agreement(agreement, user)
        entry = record_installment_payment(
            agreement, Decimal("150.00"), account, user=user
        )
        summary = agreement_summary(agreement)
        first, second = summary["rows"][:2]
        assert first[1]["paid"] == Decimal("100.00")
        assert second[1]["paid"] == Decimal("50.00")
        assert summary["outstanding"] == Decimal("850.00")

        reverse_entry(entry, user=user)
        reopened = agreement_summary(agreement)
        assert reopened["outstanding"] == Decimal("1000.00")
        assert reopened["rows"][0][1]["paid"] == Decimal("0")


@pytest.mark.django_db
def test_active_agreement_terms_and_installments_are_immutable():
    sale = SaleFactory(
        agreed_amount=Decimal("900.00"), currency="USD", status=SaleStatus.COMPLETED
    )
    user = UserFactory(company=sale.company)
    with company_scope(sale.company):
        agreement = _agreement(sale, user)
        submit_agreement(agreement, user)
        agreement = approve_agreement(agreement, user)
        agreement.cash_price = Decimal("800.00")
        with pytest.raises(ValidationError, match="immutable"):
            agreement.save()
        installment = agreement.installments.first()
        installment.amount = Decimal("1.00")
        with pytest.raises(ImmutableRecordError):
            installment.save()


@pytest.mark.django_db
def test_external_lender_payment_collection_is_rejected():
    sale = SaleFactory(
        agreed_amount=Decimal("900.00"), currency="USD", status=SaleStatus.COMPLETED
    )
    user = UserFactory(company=sale.company)
    with company_scope(sale.company):
        agreement = _agreement(sale, user)
        agreement.agreement_type = AgreementType.EXTERNAL_LENDER
        # Avoid model activation in this narrow service guard test.
        agreement.status = AgreementStatus.ACTIVE
        FinanceAgreement.all_objects.filter(pk=agreement.pk).update(
            agreement_type=AgreementType.EXTERNAL_LENDER,
            status=AgreementStatus.ACTIVE,
        )
        account = FinancialAccount.objects.create(
            company=sale.company, name="USD Cashbox", currency="USD", active=True
        )
        with pytest.raises(ValidationError, match="collected by the lender"):
            record_installment_payment(agreement, Decimal("10.00"), account, user=user)


@pytest.mark.django_db
def test_external_lender_disbursement_funds_dealership_not_installments():
    sale = SaleFactory(
        agreed_amount=Decimal("900.00"), currency="USD", status=SaleStatus.COMPLETED
    )
    user = UserFactory(company=sale.company)
    with company_scope(sale.company):
        partner = FinancingPartner.objects.create(
            company=sale.company, name="Partner Bank", partner_type="bank"
        )
        agreement = _agreement(
            sale,
            user,
            agreement_type=AgreementType.EXTERNAL_LENDER,
            partner=partner,
        )
        submit_agreement(agreement, user)
        agreement = approve_agreement(agreement, user)
        account = FinancialAccount.objects.create(
            company=sale.company, name="USD Bank", account_type="BANK", currency="USD"
        )
        entry = record_lender_disbursement(
            agreement, Decimal("900.00"), account, user=user, reference="BANK-001"
        )
        agreement.refresh_from_db()
        assert agreement.status == AgreementStatus.COMPLETED
        assert entry.lender_disbursement.partner == partner
        assert entry.installment_allocations.count() == 0
