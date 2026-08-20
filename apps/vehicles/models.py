"""Vehicle records (agent.md §10 Step 4).

Deliberately NO cost columns here: a vehicle's total cost is computed from
`purchases.VehicleCostLine` rows (§6), never stored where it can drift.
"""
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import TenantModel


class VehicleStatus(models.TextChoices):
    IN_TRANSIT = "in_transit", _("In transit")
    IN_STOCK = "in_stock", _("In stock")
    RESERVED = "reserved", _("Reserved")
    SOLD = "sold", _("Sold")
    DELIVERED = "delivered", _("Delivered")


class Vehicle(TenantModel):
    vin = models.CharField(_("VIN"), max_length=17)
    make = models.CharField(_("make"), max_length=100)
    model = models.CharField(_("model"), max_length=100)
    year = models.PositiveSmallIntegerField(_("year"))
    color = models.CharField(_("color"), max_length=50, blank=True)
    mileage = models.PositiveIntegerField(_("mileage (km)"), default=0)
    status = models.CharField(
        _("status"), max_length=20, choices=VehicleStatus.choices, default=VehicleStatus.IN_TRANSIT
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="vehicles",
        verbose_name=_("branch"),
        null=True,
        blank=True,
    )
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("vehicle")
        verbose_name_plural = _("vehicles")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["company", "vin"], name="unique_vin_per_company")
        ]

    def __str__(self):
        return f"{self.year} {self.make} {self.model} ({self.vin})"

    @property
    def primary_photo(self):
        """Oldest vehicle photo (card thumbnail). Prefetched `photo_list`
        (set by the list view) avoids a query per card; falls back to a
        scoped query on direct use (e.g. the detail page)."""
        photo_list = getattr(self, "photo_list", None)
        if photo_list is not None:
            return photo_list[0] if photo_list else None
        from apps.documents.models import Document, DocumentType

        return (
            self.documents.filter(doc_type=DocumentType.VEHICLE_PHOTO)
            .order_by("created_at", "pk")
            .first()
        )

    def get_absolute_url(self):
        return reverse("vehicles:detail", kwargs={"pk": self.pk})
