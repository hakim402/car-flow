"""Audit wiring (agent.md §10 Step 8): django-simple-history is attached to
tenant-scoped models from this single place so business models stay clean.

Financial rows (`LedgerEntry`, `VehicleCostLine`, `Invoice`) are deliberately
NOT registered: they are already immutable append-only rows (§6), and history
tracking on them would only duplicate that guarantee.
"""
from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "apps.audit"
    verbose_name = "Audit"

    def ready(self):
        from simple_history import register

        from apps.customers.models import Customer
        from apps.inventory.models import VehicleStock
        from apps.purchases.models import PurchaseOrder
        from apps.sales.models import Lead, Quotation, Reservation, Sale
        from apps.suppliers.models import Supplier
        from apps.vehicles.models import Vehicle

        for model in (
            Vehicle,
            VehicleStock,
            Supplier,
            PurchaseOrder,
            Customer,
            Lead,
            Quotation,
            Reservation,
            Sale,
        ):
            register(model)
