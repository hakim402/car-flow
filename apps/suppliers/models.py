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


class Supplier(TenantModel):
    name = models.CharField(_("name"), max_length=200)
    supplier_type = models.CharField(
        _("supplier type"),
        max_length=20,
        choices=SupplierType.choices,
        default=SupplierType.LOCAL_DEALER,
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
