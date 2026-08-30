import pytest

from apps.customers.forms import CustomerForm
from apps.sales.forms import LeadForm, QuotationForm, ReservationForm


@pytest.mark.django_db
def test_customer_form_has_help_text_for_core_fields():
    form = CustomerForm()
    for field_name in ["full_name", "phone", "email", "national_id", "branch", "notes"]:
        assert field_name in form.fields
        assert form.fields[field_name].help_text, f"Missing help text for {field_name}"


@pytest.mark.django_db
def test_sales_forms_include_agent_required_crm_fields():
    lead_form = LeadForm()
    for field_name in ["assigned_to", "lost_reason"]:
        assert field_name in lead_form.fields
        assert lead_form.fields[field_name].help_text, f"Missing help text for {field_name}"

    quotation_form = QuotationForm()
    assert "number" in quotation_form.fields
    assert quotation_form.fields["number"].help_text

    reservation_form = ReservationForm()
    assert "expires_at" in reservation_form.fields
    assert reservation_form.fields["expires_at"].help_text
