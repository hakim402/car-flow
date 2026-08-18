from django.db import models
from django.utils.translation import gettext_lazy as _


class Organization(models.Model):
    """A tenant (company/dealership group). Root of the tenant hierarchy —
    Organization itself is NOT tenant-scoped; it IS the tenant (§5)."""

    name = models.CharField(_("name"), max_length=200)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("organization")
        verbose_name_plural = _("organizations")
        ordering = ["name"]

    def __str__(self):
        return self.name
