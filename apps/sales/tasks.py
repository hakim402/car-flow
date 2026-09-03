"""Scheduled sales workflows."""

from celery import shared_task
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.tenancy import company_scope
from apps.inventory.models import StockStatus
from apps.inventory.services import release_stock

from .models import Reservation, ReservationStatus


@shared_task
def expire_reservations() -> int:
    """Expire overdue active reservations and release their inventory."""
    now = timezone.now()
    candidates = list(
        Reservation.all_objects.filter(
            status=ReservationStatus.ACTIVE,
            expires_at__isnull=False,
            expires_at__lte=now,
        ).values_list("pk", "company_id")
    )
    expired = 0
    for reservation_id, company_id in candidates:
        with company_scope(company_id), transaction.atomic():
            reservation = (
                Reservation.objects.select_for_update()
                .select_related("vehicle", "vehicle__stock")
                .filter(
                    pk=reservation_id,
                    status=ReservationStatus.ACTIVE,
                    expires_at__lte=now,
                )
                .first()
            )
            if reservation is None:
                continue
            stock = getattr(reservation.vehicle, "stock", None)
            if stock is not None and stock.status in {
                StockStatus.RESERVED,
                StockStatus.AVAILABLE,
            }:
                try:
                    release_stock(
                        reservation.vehicle,
                        notes=f"Reservation #{reservation.pk} expired",
                    )
                except ValidationError:
                    continue
            reservation.status = ReservationStatus.EXPIRED
            reservation.save(update_fields=["status", "updated_at"])
            expired += 1
    return expired
