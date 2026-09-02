"""Vehicle records (agent.md §10 Step 4).

Deliberately NO cost columns here: a vehicle's total cost is computed from
`purchases.VehicleCostLine` rows (§6), never stored where it can drift.

Inventory state is authoritative on `inventory.VehicleStock` (§8); the
legacy `status` mirror below is DEPRECATED and kept only for migration
history. It will be removed in a later migration once no code depends on it.
"""
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.models import CompanyConsistencyMixin
from apps.core.tenancy import TenantModel


class VehicleStatus(models.TextChoices):
    """DEPRECATED (Phase 2): superseded by `inventory.StockStatus`.

    Kept only so existing rows survive migration history. Do not read or
    write this in new code; the authoritative lifecycle is VehicleStock.status.
    """

    IN_TRANSIT = "in_transit", _("In transit")
    IN_STOCK = "in_stock", _("In stock")
    RESERVED = "reserved", _("Reserved")
    SOLD = "sold", _("Sold")
    DELIVERED = "delivered", _("Delivered")


class FuelType(models.TextChoices):
    PETROL = "petrol", _("Petrol")
    DIESEL = "diesel", _("Diesel")
    HYBRID = "hybrid", _("Hybrid")
    ELECTRIC = "electric", _("Electric")
    LPG = "lpg", _("LPG")
    OTHER = "other", _("Other")


class TransmissionType(models.TextChoices):
    MANUAL = "manual", _("Manual")
    AUTOMATIC = "automatic", _("Automatic")
    CVT = "cvt", _("CVT")
    DUAL_CLUTCH = "dual_clutch", _("Dual clutch")
    OTHER = "other", _("Other")


class DriveType(models.TextChoices):
    FWD = "fwd", _("Front-wheel drive")
    RWD = "rwd", _("Rear-wheel drive")
    AWD = "awd", _("All-wheel drive")
    FOUR_BY_FOUR = "4x4", _("4x4")
    OTHER = "other", _("Other")


class BodyType(models.TextChoices):
    SEDAN = "sedan", _("Sedan")
    HATCHBACK = "hatchback", _("Hatchback")
    SUV = "suv", _("SUV")
    PICKUP = "pickup", _("Pickup")
    VAN = "van", _("Van")
    COUPE = "coupe", _("Coupe")
    TRUCK = "truck", _("Truck")
    OTHER = "other", _("Other")


class Vehicle(TenantModel, CompanyConsistencyMixin):
    company_relations = ("branch",)

    vin = models.CharField(_("VIN"), max_length=17, help_text=_("17-character vehicle identification number."))
    plate_number = models.CharField(_("plate number"), max_length=50, blank=True, help_text=_("Current registration plate or number plate."))
    registration_number = models.CharField(_("registration number"), max_length=100, blank=True, help_text=_("Official registration or document reference."))
    engine_number = models.CharField(_("engine number"), max_length=100, blank=True, help_text=_("Engine serial or identification number."))
    chassis_number = models.CharField(_("chassis number"), max_length=100, blank=True, help_text=_("Chassis or frame number."))
    make = models.CharField(_("make"), max_length=100, help_text=_("Manufacturer or brand of the vehicle."))
    model = models.CharField(_("model"), max_length=100, help_text=_("Vehicle model name or series."))
    model_variant = models.CharField(_("model variant"), max_length=100, blank=True, help_text=_("Trim, variant, or package name."))
    year = models.PositiveSmallIntegerField(_("year"), help_text=_("Model year as shown on the vehicle registration."))
    color = models.CharField(_("color"), max_length=50, blank=True, help_text=_("Vehicle paint or body color."))
    mileage = models.PositiveIntegerField(_("mileage (km)"), default=0, help_text=_("Current odometer reading in kilometers."))
    body_type = models.CharField(_("body type"), max_length=20, choices=BodyType.choices, default=BodyType.OTHER, blank=True, help_text=_("Vehicle body style."))
    fuel_type = models.CharField(_("fuel type"), max_length=20, choices=FuelType.choices, default=FuelType.PETROL, blank=True, help_text=_("Primary fuel or energy type."))
    transmission = models.CharField(_("transmission"), max_length=20, choices=TransmissionType.choices, default=TransmissionType.AUTOMATIC, blank=True, help_text=_("Transmission type."))
    drive_type = models.CharField(_("drive type"), max_length=20, choices=DriveType.choices, default=DriveType.FWD, blank=True, help_text=_("Drive configuration."))
    door_count = models.PositiveSmallIntegerField(_("door count"), default=4, blank=True, help_text=_("Number of doors."))
    seating_capacity = models.PositiveSmallIntegerField(_("seating capacity"), default=5, blank=True, help_text=_("Passenger seating capacity."))
    country_of_origin = models.CharField(_("country of origin"), max_length=5, blank=True, help_text=_("Country where the vehicle was built or imported from."))
    first_registration_date = models.DateField(_("first registration date"), null=True, blank=True, help_text=_("Date of first registration, if known."))
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=VehicleStatus.choices,
        default=VehicleStatus.IN_TRANSIT,
        help_text=_(
            "Deprecated: the authoritative inventory state lives on "
            "inventory.VehicleStock.status (§8). Do not use."
        ),
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="vehicles",
        verbose_name=_("branch"),
        null=True,
        blank=True,
        help_text=_("Branch where this vehicle is assigned or stored."),
    )
    notes = models.TextField(_("notes"), blank=True, help_text=_("Internal notes, condition comments, or handling details."))
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
            return next((photo for photo in photo_list if photo.file_exists), None)
        from apps.documents.models import Document, DocumentType

        photos = (
            self.documents.filter(doc_type=DocumentType.VEHICLE_PHOTO)
            .order_by("created_at", "pk")
        )
        return next((photo for photo in photos if photo.file_exists), None)

    def get_absolute_url(self):
        return reverse("vehicles:detail", kwargs={"pk": self.pk})

    @property
    def source_supplier(self):
        """Supplier this car was bought from (via its purchase-order lines).

        The list view prefetches lines into `purchase_line_list`; fall back
        to a scoped query on direct use (e.g. the detail page)."""
        line_list = getattr(self, "purchase_line_list", None)
        if line_list is not None:
            line = line_list[0] if line_list else None
        else:
            line = self.purchase_lines.select_related("order__supplier").first()
        return line.order.supplier if line is not None else None
