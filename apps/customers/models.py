"""Customer records (agent.md §10 Step 6).

A customer is the tenant-scoped person a lead converts into; every later
pipeline stage (quotation, reservation, sale, invoice) references one.
"""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import TenantModel


class Customer(TenantModel):
    full_name = models.CharField(_("full name"), max_length=200)
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    email = models.EmailField(_("email"), blank=True)
    national_id = models.CharField(_("national ID"), max_length=50, blank=True)
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="customers",
        verbose_name=_("branch"),
        null=True,
        blank=True,
    )
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_customers",
        verbose_name=_("created by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("customer")
        verbose_name_plural = _("customers")
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    def get_absolute_url(self):
        return reverse("customers:detail", kwargs={"pk": self.pk})
