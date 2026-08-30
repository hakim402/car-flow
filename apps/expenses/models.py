from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import TenantModel


class ExpenseCategory(TenantModel):
    """Operating expense classification used by the expense ledger."""

    name = models.CharField(_("name"), max_length=200)
    code = models.CharField(_("code"), max_length=50, blank=True)
    active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("expense category")
        verbose_name_plural = _("expense categories")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="unique_expense_category_name_per_company",
            )
        ]

    def __str__(self):
        return self.name
