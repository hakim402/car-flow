from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.constants import COUNTRIES
from apps.core.tenancy import TenantModel


class SupplierType(models.TextChoices):
    LOCAL_DEALER = "local_dealer", _("Local dealer")
    OVERSEAS_DEALER = "overseas_dealer", _("Overseas dealer")
    AUCTION = "auction", _("Auction house")
    BROKER = "broker", _("Broker / agent")
    SHIPPING_AGENT = "shipping_agent", _("Shipping / clearing agent")
    OTHER = "other", _("Other")


class SupplierKind(models.TextChoices):
    """Cars are sometimes bought from private people, not just companies
    (§9): an individual supplier carries personal ID data (tazkera/passport)
    instead of business paperwork."""

    BUSINESS = "business", _("Business")
    INDIVIDUAL = "individual", _("Individual (person)")


class Supplier(TenantModel):
    name = models.CharField(_("name"), max_length=200)
    kind = models.CharField(
        _("kind"),
        max_length=20,
        choices=SupplierKind.choices,
        default=SupplierKind.BUSINESS,
    )
    supplier_type = models.CharField(
        _("supplier type"),
        max_length=20,
        choices=SupplierType.choices,
        default=SupplierType.LOCAL_DEALER,
    )
    national_id = models.CharField(
        _("tazkera / national ID no."), max_length=50, blank=True
    )
    country = models.CharField(
        _("country"), max_length=5, choices=COUNTRIES, blank=True
    )
    contact_person = models.CharField(_("contact person"), max_length=200, blank=True)
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    email = models.EmailField(_("email"), blank=True)
    address = models.TextField(_("address"), blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("supplier")
        verbose_name_plural = _("suppliers")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("suppliers:detail", kwargs={"pk": self.pk})

    @property
    def is_individual(self):
        return self.kind == SupplierKind.INDIVIDUAL

    @property
    def logo(self):
        """Most recent logo/portrait document, if any.

        Businesses upload a logo, private sellers a portrait photo — both
        serve as the supplier's picture. The list view prefetches them into
        a `logo_list` attribute; fall back to a scoped query otherwise.
        """
        logo_list = getattr(self, "logo_list", None)
        if logo_list is not None:
            return logo_list[0] if logo_list else None
        from apps.documents.models import Document, DocumentType

        return (
            self.documents.filter(
                doc_type__in=(DocumentType.SUPPLIER_LOGO, DocumentType.SUPPLIER_PHOTO)
            )
            .order_by("-created_at", "-pk")
            .first()
        )
