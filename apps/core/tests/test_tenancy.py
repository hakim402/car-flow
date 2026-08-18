"""Tenant isolation gate (agent.md §5, §10 Step 12).

Cross-company reads must be impossible through the default manager, and
bulk writes through it must only ever touch the current tenant's rows.
"""
import pytest

from apps.core.tenancy import (
    NoTenantContext,
    company_scope,
    get_current_company,
    reset_current_company,
    set_current_company,
)
from apps.core.testing import OrganizationFactory, VehicleFactory
from apps.vehicles.models import Vehicle


@pytest.fixture
def two_companies(db):
    return OrganizationFactory(), OrganizationFactory()


@pytest.mark.django_db
def test_default_manager_hides_other_companies(two_companies):
    company_a, company_b = two_companies
    vehicle_a = VehicleFactory(company=company_a)
    VehicleFactory(company=company_b)

    with company_scope(company_a):
        assert list(Vehicle.objects.all()) == [vehicle_a]
        assert Vehicle.objects.count() == 1


@pytest.mark.django_db
def test_foreign_row_lookup_raises(two_companies):
    company_a, company_b = two_companies
    VehicleFactory(company=company_a)
    foreign = VehicleFactory(company=company_b)

    with company_scope(company_a):
        with pytest.raises(Vehicle.DoesNotExist):
            Vehicle.objects.get(pk=foreign.pk)


@pytest.mark.django_db
def test_all_objects_escape_hatch_sees_everything(two_companies):
    company_a, company_b = two_companies
    VehicleFactory(company=company_a)
    VehicleFactory(company=company_b)

    with company_scope(company_a):
        assert Vehicle.all_objects.count() == 2


@pytest.mark.django_db
def test_bulk_update_only_touches_current_tenant(two_companies):
    company_a, company_b = two_companies
    VehicleFactory(company=company_a)
    vehicle_b = VehicleFactory(company=company_b)

    with company_scope(company_a):
        updated = Vehicle.objects.update(notes="scoped write")
    assert updated == 1

    vehicle_b.refresh_from_db()
    assert vehicle_b.notes == ""


@pytest.mark.django_db
def test_bulk_delete_only_touches_current_tenant(two_companies):
    company_a, company_b = two_companies
    VehicleFactory(company=company_a)
    vehicle_b = VehicleFactory(company=company_b)

    with company_scope(company_a):
        deleted, _ = Vehicle.objects.all().delete()
    assert deleted == 1
    assert Vehicle.all_objects.filter(pk=vehicle_b.pk).exists()


@pytest.mark.django_db
def test_explicit_query_requires_tenant_context(two_companies):
    company_a, _ = two_companies
    VehicleFactory(company=company_a)
    # Outside any request/scope there is no implicit tenant — the explicit
    # helper must refuse instead of guessing.
    assert get_current_company() is None
    with pytest.raises(NoTenantContext):
        Vehicle.objects.for_current_company()


@pytest.mark.django_db
def test_company_scope_restores_previous_context(two_companies):
    company_a, company_b = two_companies
    token = set_current_company(company_a)
    try:
        with company_scope(company_b):
            assert get_current_company() == company_b
        assert get_current_company() == company_a
    finally:
        reset_current_company(token)
