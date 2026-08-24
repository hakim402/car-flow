"""The `integrity_audit` management command (Phase 1).

Read-only, cross-tenant scan using the explicit `all_objects` escape hatch
(§25.1). Most integrity classes are already DB-constrained, so only
cross-company FKs can be injected here — the audit exists to catch rows
written before the constraints and violations the DB cannot express.
"""
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.testing import CustomerFactory, SaleFactory
from apps.sales.models import Sale


@pytest.mark.django_db
def test_audit_passes_on_clean_database(capsys):
    SaleFactory()
    call_command("integrity_audit")
    assert "Integrity audit passed" in capsys.readouterr().out


@pytest.mark.django_db
def test_audit_detects_cross_company_sale(capsys):
    foreign_customer = CustomerFactory()  # its own company
    sale = SaleFactory()  # a different company
    sale.customer_id = foreign_customer.pk
    sale.save()  # save() skips clean(): simulates pre-constraint/import data

    with pytest.raises(CommandError):
        call_command("integrity_audit")
    captured = capsys.readouterr()
    assert "same-company relations" in captured.err
    assert f"Sale #{sale.pk}" in captured.err


@pytest.mark.django_db
def test_audit_company_scope_skips_other_tenants(capsys):
    foreign_customer = CustomerFactory()  # its own company
    sale = SaleFactory()  # a different company
    sale.customer_id = foreign_customer.pk
    sale.save()

    # The violating row belongs to `sale.company`; auditing the OTHER company
    # must not report it.
    with pytest.raises(CommandError):
        call_command("integrity_audit", company=Sale.all_objects.get(pk=sale.pk).company_id)
    call_command("integrity_audit", company=foreign_customer.company_id)
    assert "Integrity audit passed" in capsys.readouterr().out
