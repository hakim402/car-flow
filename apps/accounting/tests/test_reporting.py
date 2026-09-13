import json
from datetime import date
from decimal import Decimal

import pytest
from django.core.serializers.json import DjangoJSONEncoder

from apps.accounting.report_forms import ReportFilterForm
from apps.accounting.reporting import REPORTS, build_report
from apps.branches.models import Branch
from apps.core.tenancy import NoTenantContext, company_scope
from apps.core.testing import OrganizationFactory, SaleFactory
from apps.payments.models import EntryType, LedgerEntry

pytestmark = pytest.mark.django_db


def _entry(company, **kwargs):
    defaults = dict(type=EntryType.CUSTOMER_PAYMENT, amount=Decimal("20"), currency="USD", transaction_date=date(2026, 1, 5))
    return LedgerEntry.objects.create(company=company, **{**defaults, **kwargs})


def test_activity_filter_rejects_bad_dates_and_foreign_branch():
    company, other = OrganizationFactory(), OrganizationFactory()
    foreign = Branch.objects.create(company=other, name="Other")
    form = ReportFilterForm({"date_from": "2026-02-01", "date_to": "2026-01-01", "branch": foreign.pk}, company=company, report_key="activity")
    assert not form.is_valid()
    assert {"date_to", "branch"} <= set(form.errors)
    assert not ReportFilterForm({"date_from": "not-a-date"}, company=company, report_key="activity").is_valid()
    activity = ReportFilterForm({}, company=company, report_key="activity")
    assert {"date_from", "date_to", "branch", "q", "action", "module"} == set(activity.fields)
    assert "currency" not in activity.fields


def test_reports_fail_closed_without_company():
    with pytest.raises(NoTenantContext):
        build_report("activity", {})


def test_only_business_activity_report_remains_in_catalog():
    assert set(REPORTS) == {"activity"}


def test_activity_report_has_serializable_complete_schema():
    company = OrganizationFactory()
    with company_scope(company):
        result = build_report("activity", {})
    assert result["key"] == "activity"
    assert result["columns"]
    assert all(column["kind"] in {"text", "money", "number", "date"} for column in result["columns"])
    json.dumps(result, cls=DjangoJSONEncoder)


@pytest.mark.parametrize("key", [
    "summary", "cash-position", "expenses", "profitability", "sales", "stock",
    "purchases", "financing", "contacts", "receivables", "payables",
    "communications", "documents",
])
def test_removed_reports_are_not_in_catalog_and_fail_closed(key):
    assert key not in REPORTS
    company = OrganizationFactory()
    with company_scope(company):
        with pytest.raises(KeyError):
            build_report(key, {})


def test_activity_report_records_business_history_and_filters():
    company = OrganizationFactory()
    sale = SaleFactory(company=company, status="completed", agreed_amount=Decimal("100"), sale_date=date(2026, 1, 1))
    with company_scope(company):
        report = build_report("activity", {"module": "sales", "action": "+", "date_from": date(2026, 1, 1), "date_to": date(2026, 12, 31)})
    assert report["rows"]
    assert all(row["module_key"] == "sales" for row in report["rows"])
    assert all(row["action_key"] == "+" for row in report["rows"])
    assert any(str(sale.pk) in row["reference"] for row in report["rows"])
    labels = {metric["label"] for metric in report["metrics"]}
    assert {"Recorded changes", "Created records", "Active staff", "Updated records"} <= labels
    assert [chart["title"] for chart in report["charts"]] == ["Changes over time"]


def test_installment_cutoff_ignores_later_receipts_and_reversals():
    from apps.financing.models import FinanceAgreement, Installment, PaymentAllocation
    from apps.financing.services import installment_summary
    company = OrganizationFactory()
    sale = SaleFactory(company=company, agreed_amount=Decimal("100"), sale_date=date(2026, 1, 1))
    with company_scope(company):
        agreement = FinanceAgreement.objects.create(company=company, sale=sale, number="TEST-CUTOFF", currency="USD", cash_price=Decimal("100"),
                                                    down_payment_required=0, installment_count=1, frequency="monthly", first_due_date=date(2026, 1, 15))
        installment = Installment.objects.create(company=company, agreement=agreement, sequence=1, due_date=date(2026, 1, 15), amount=Decimal("100"))
        receipt = _entry(company, sale=sale, amount=Decimal("40"))
        PaymentAllocation.objects.create(company=company, installment=installment, entry=receipt, amount=Decimal("40"))
        later = _entry(company, sale=sale, amount=Decimal("10"), transaction_date=date(2026, 2, 1))
        PaymentAllocation.objects.create(company=company, installment=installment, entry=later, amount=Decimal("10"))
        _entry(company, sale=sale, amount=Decimal("40"), reversal_of=receipt, transaction_date=date(2026, 2, 10))
        assert installment_summary(installment, date(2026, 1, 31))["paid"] == Decimal("40")
        assert installment_summary(installment, date(2026, 2, 5))["paid"] == Decimal("50")
        assert installment_summary(installment, date(2026, 2, 28))["paid"] == Decimal("10")
