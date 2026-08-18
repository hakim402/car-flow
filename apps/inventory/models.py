"""Branch-scoped stock records (agent.md §4/§5).

One VehicleStock row per vehicle currently held at a branch; purchase receipt
(Step 5) creates them, sales/delivery (Step 6) retire them.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import TenantModel


class StockStatus(models.TextChoices):
    AVAILABLE = "available", _("Available")
    RESERVED = "reserved", _("Reserved")
    IN_PREPARATION = "in_preparation", _("In preparation")


class VehicleStock(TenantModel):
    vehicle = models.OneToOneField(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="stock",
        verbose_name=_("vehicle"),
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="stock",
        verbose_name=_("branch"),
    )
    status = models.CharField(
        _("status"), max_length=20, choices=StockStatus.choices, default=StockStatus.AVAILABLE
    )
    lot_code = models.CharField(_("lot / parking code"), max_length=50, blank=True)
    received_at = models.DateTimeField(_("received at"), auto_now_add=True)

    class Meta:
        verbose_name = _("vehicle stock")
        verbose_name_plural = _("vehicle stock")
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.vehicle} @ {self.branch}"
