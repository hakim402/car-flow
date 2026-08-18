from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import TenantModel


class Supplier(TenantModel):
    name = models.CharField(_("name"), max_length=200)
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
        return reverse("suppliers:edit", kwargs={"pk": self.pk})
