"""Vehicle photos/documents and customer uploads (agent.md §10 Step 10).

Storage location is NOT decided here: `FileField` writes through Django's
default storage, which the settings layer switches between the local
`media/` volume and S3 based on `S3_ENABLED` (§12.2).
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import TenantModel


class DocumentType(models.TextChoices):
    VEHICLE_PHOTO = "vehicle_photo", _("Vehicle photo")
    VEHICLE_DOCUMENT = "vehicle_document", _("Vehicle document")
    CUSTOMER_DOCUMENT = "customer_document", _("Customer document")
    OTHER = "other", _("Other")


class Document(TenantModel):
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("vehicle"),
        null=True,
        blank=True,
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("customer"),
        null=True,
        blank=True,
    )
    doc_type = models.CharField(
        _("type"), max_length=30, choices=DocumentType.choices, default=DocumentType.OTHER
    )
    title = models.CharField(_("title"), max_length=255, blank=True)
    file = models.FileField(_("file"), upload_to="documents/%Y/%m/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_documents",
        verbose_name=_("uploaded by"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("document")
        verbose_name_plural = _("documents")
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or self.file.name
