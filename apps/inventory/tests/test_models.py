"""Model-level guarantees of the Phase 2 inventory architecture (README §8):
status/condition dimensions, aging derivation and the per-branch location
code uniqueness constraint."""
import datetime

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.branches.models import Branch
from apps.core.tenancy import company_scope
from apps.core.testing import OrganizationFactory, VehicleFactory
from apps.inventory.aging import (
    AGE_BUCKET_LABELS,
    bucket_for_days,
    inventory_aging,
    stock_age_bucket,
)
from apps.inventory.models import (
    InventoryLocation,
    StockStatus,
    VehicleCondition,
    VehicleStock,
)


@pytest.mark.django_db
def test_stock_status_lifecycle_is_complete():
    """The lifecycle covers receiving through delivery (§8.2)."""
    assert StockStatus.values == [
        "in_transit",
        "received",
        "inspection",
        "preparation",
        "available",
        "reserved",
        "sold",
        "delivered",
    ]


@pytest.mark.django_db
def test_condition_is_a_separate_dimension():
    """Condition (physical) and status (availability) are independent (§8.2)."""
    assert "damaged" in VehicleCondition.values
    assert "damaged" not in StockStatus.values


@pytest.mark.django_db
def test_location_code_unique_per_branch_only_when_populated():
    company = OrganizationFactory()
    branch = Branch.objects.create(company=company, name="HQ")
    other_branch = Branch.objects.create(company=company, name="South")
    InventoryLocation.all_objects.create(company=company, branch=branch, name="A", code="SH-01")

    # Same code on the SAME branch collides.
    with pytest.raises(IntegrityError), transaction.atomic():
        InventoryLocation.all_objects.create(company=company, branch=branch, name="B", code="SH-01")

    # Same code on another branch (or blank codes) is fine.
    InventoryLocation.all_objects.create(company=company, branch=other_branch, name="C", code="SH-01")
    InventoryLocation.all_objects.create(company=company, branch=branch, name="D", code="")
    InventoryLocation.all_objects.create(company=company, branch=branch, name="E", code="")


@pytest.mark.django_db
def test_aging_derives_from_dated_columns():
    company = OrganizationFactory()
    vehicle = VehicleFactory(company=company)
    branch = Branch.objects.create(company=company, name="HQ")
    received = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
    stock = VehicleStock.all_objects.create(
        company=company,
        vehicle=vehicle,
        branch=branch,
        received_at=received,
        sold_at=received + datetime.timedelta(days=45),
    )
    today = received.date() + datetime.timedelta(days=100)
    assert stock.days_in_inventory == (timezone.localdate() - received.date()).days
    assert stock.days_to_sale == 45
    assert stock.days_to_delivery is None  # not delivered yet

    stock.delivered_at = received + datetime.timedelta(days=52)
    assert stock.days_to_delivery == 52


@pytest.mark.django_db
def test_age_buckets_map_days():
    assert bucket_for_days(0) == "0_30"
    assert bucket_for_days(30) == "0_30"
    assert bucket_for_days(31) == "31_60"
    assert bucket_for_days(60) == "31_60"
    assert bucket_for_days(61) == "61_90"
    assert bucket_for_days(90) == "61_90"
    assert bucket_for_days(91) == "90_plus"
    assert bucket_for_days(365) == "90_plus"
    assert set(AGE_BUCKET_LABELS) == {"0_30", "31_60", "61_90", "90_plus"}


@pytest.mark.django_db
def test_stock_age_bucket_and_aggregate():
    company = OrganizationFactory()
    branch = Branch.objects.create(company=company, name="HQ")
    today = datetime.date(2026, 8, 24)

    def make_stock(age_days, status):
        vehicle = VehicleFactory(company=company)
        return VehicleStock.all_objects.create(
            company=company,
            vehicle=vehicle,
            branch=branch,
            status=status,
            received_at=timezone.make_aware(datetime.datetime.combine(today - datetime.timedelta(days=age_days), datetime.time())),
        )

    fresh = make_stock(10, StockStatus.AVAILABLE)
    aged = make_stock(75, StockStatus.AVAILABLE)
    sold = make_stock(200, StockStatus.SOLD)  # left inventory: excluded

    assert stock_age_bucket(fresh, today=today) == "0_30"
    assert stock_age_bucket(aged, today=today) == "61_90"
    with company_scope(company):
        counts = inventory_aging(today=today)
    assert counts["0_30"] == 1
    assert counts["61_90"] == 1
    assert counts["90_plus"] == 0
    assert sold.pk  # still exists — never deleted on sale
