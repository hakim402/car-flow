from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.branches.models import Branch
from apps.core.tenancy import company_scope
from apps.core.testing import CustomerFactory, OrganizationFactory, SaleFactory, VehicleFactory
from apps.inventory.models import StockStatus
from apps.inventory.services import adjust_stock_status, receive_vehicle, reserve_stock
from apps.sales.models import Reservation, ReservationStatus, SaleStatus
from apps.sales.services import complete_sale
from apps.sales.tasks import expire_reservations


def _available_vehicle(company):
    branch = Branch.objects.create(company=company, name="Main")
    vehicle = VehicleFactory(company=company, branch=branch)
    with company_scope(company):
        stock = receive_vehicle(vehicle, branch)
        adjust_stock_status(stock, StockStatus.AVAILABLE)
    return vehicle


@pytest.mark.django_db
def test_vehicle_cannot_be_completed_in_two_sales():
    company = OrganizationFactory()
    vehicle = _available_vehicle(company)
    first = SaleFactory(company=company, vehicle=vehicle)

    with company_scope(company):
        assert complete_sale(first)
        second = SaleFactory(company=company, vehicle=vehicle)
        with pytest.raises(ValidationError, match="already has a completed sale"):
            complete_sale(second)

    second.refresh_from_db()
    assert second.status == SaleStatus.DRAFT


@pytest.mark.django_db
def test_expired_reservation_releases_vehicle_stock():
    company = OrganizationFactory()
    vehicle = _available_vehicle(company)
    customer = CustomerFactory(company=company)
    with company_scope(company):
        reserve_stock(vehicle)
        reservation = Reservation.objects.create(
            company=company,
            customer=customer,
            vehicle=vehicle,
            deposit_amount="500.00",
            currency="USD",
            expires_at=timezone.now() - timedelta(minutes=1),
        )

    assert expire_reservations() == 1
    reservation.refresh_from_db()
    vehicle.stock.refresh_from_db()
    assert reservation.status == ReservationStatus.EXPIRED
    assert vehicle.stock.status == StockStatus.AVAILABLE
