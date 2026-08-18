"""Computed aggregates over cost rows (§6: current-state values are computed,
never stored). Returns per-currency totals — conversion happens only at the
display layer (§9), never here."""
from decimal import Decimal

from .models import VehicleCostLine


def vehicle_landed_cost(vehicle) -> dict[str, Decimal]:
    """Total cost of a vehicle across all cost lines, grouped by currency."""
    totals: dict[str, Decimal] = {}
    for row in VehicleCostLine.objects.filter(vehicle=vehicle):
        totals[row.currency] = totals.get(row.currency, Decimal("0")) + row.amount
    return totals
