from django.db import models
from django.utils.translation import gettext_lazy as _


class Branch(models.Model):
    """Child scope under Organization (§5). Branch-specific models (Sales,
    Inventory) carry a Branch FK alongside their tenant company FK."""

    company = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="branches",
        verbose_name=_("company"),
    )
    name = models.CharField(_("name"), max_length=200)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("branch")
        verbose_name_plural = _("branches")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="unique_branch_name_per_company"
            )
        ]

    def __str__(self):
        return self.name
