"""Inventory aging, derived from dated columns — never stored (§8.4)."""
from collections import OrderedDict

from django.utils import timezone

from .models import StockStatus

# (upper-bound days, bucket key) — None = unbounded.
AGE_BUCKETS = (
    (30, "0_30"),
    (60, "31_60"),
    (90, "61_90"),
    (None, "90_plus"),
)

AGE_BUCKET_LABELS = {
    "0_30": "0-30 days",
    "31_60": "31-60 days",
    "61_90": "61-90 days",
    "90_plus": "90+ days",
}


def bucket_for_days(days):
    """Map an age in days to its dashboard bucket (§8.4)."""
    for limit, key in AGE_BUCKETS:
        if limit is None or days <= limit:
            return key
    return "90_plus"


def stock_age_bucket(stock, today=None):
    if stock.received_at is None:
        return None
    today = today or timezone.localdate()
    return bucket_for_days((today - stock.received_at.date()).days)


def inventory_aging(active_queryset=None, today=None):
    """Counts of current inventory per age bucket. Active = vehicles that
    have not left inventory (SOLD/DELIVERED rows are kept but excluded)."""
    from .models import VehicleStock

    queryset = active_queryset or VehicleStock.objects.exclude(
        status__in=[StockStatus.SOLD, StockStatus.DELIVERED]
    )
    counts = OrderedDict((key, 0) for _, key in AGE_BUCKETS)
    for stock in queryset.only("received_at"):
        bucket = stock_age_bucket(stock, today=today)
        if bucket is not None:
            counts[bucket] += 1
    return counts
