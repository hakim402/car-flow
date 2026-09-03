"""Vehicle photos/documents and customer uploads (agent.md §10 Step 10).

Storage location is NOT decided here: `FileField` writes through Django's
default storage, which the settings layer switches between the local
`media/` volume and S3 based on `S3_ENABLED` (§12.2).
"""
import logging
from functools import cached_property

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CompanyConsistencyMixin
from apps.core.tenancy import TenantModel


logger = logging.getLogger(__name__)


class DocumentType(models.TextChoices):
    VEHICLE_PHOTO = "vehicle_photo", _("Vehicle photo")
    LICENSE = "license", _("Vehicle license")
    SALE_DOCUMENT = "sale_document", _("Sale document")
    INSURANCE = "insurance", _("Insurance policy")
    CUSTOMS = "customs", _("Customs / import document")
    INSPECTION = "inspection", _("Inspection report")
    VEHICLE_DOCUMENT = "vehicle_document", _("Other vehicle document")
    CUSTOMER_PHOTO = "customer_photo", _("Customer photo")
    TAZKERA = "tazkera", _("Tazkera (national ID)")
    PASSPORT = "passport", _("Passport")
    ELECTRICITY_BILL = "electricity_bill", _("Electricity bill")
    OTHER_BILL = "other_bill", _("Other bill")
    CUSTOMER_DOCUMENT = "customer_document", _("Other customer document")
    SUPPLIER_LOGO = "supplier_logo", _("Supplier logo / photo")
    SUPPLIER_PHOTO = "supplier_photo", _("Supplier portrait photo")
    SUPPLIER_LICENSE = "supplier_license", _("Supplier business license")
    SUPPLIER_DOCUMENT = "supplier_document", _("Other supplier document")
    FINANCE_AGREEMENT = "finance_agreement", _("Signed financing agreement")
    GUARANTOR_DOCUMENT = "guarantor_document", _("Guarantor document")
    OTHER = "other", _("Other")


#: Types a vehicle upload box may create (everything customer-unrelated).
VEHICLE_DOC_TYPES = [
    DocumentType.VEHICLE_PHOTO,
    DocumentType.LICENSE,
    DocumentType.SALE_DOCUMENT,
    DocumentType.INSURANCE,
    DocumentType.CUSTOMS,
    DocumentType.INSPECTION,
    DocumentType.VEHICLE_DOCUMENT,
]

#: Types a customer upload box may create (identity docs, bills, photos).
CUSTOMER_DOC_TYPES = [
    DocumentType.CUSTOMER_PHOTO,
    DocumentType.TAZKERA,
    DocumentType.PASSPORT,
    DocumentType.ELECTRICITY_BILL,
    DocumentType.OTHER_BILL,
    DocumentType.CUSTOMER_DOCUMENT,
]

#: Types a supplier upload box may create. Businesses upload logos and
#: licenses; private sellers (individuals) upload portraits, tazkera/passport
#: and the car paperwork tied to the sale.
SUPPLIER_DOC_TYPES = [
    DocumentType.SUPPLIER_LOGO,
    DocumentType.SUPPLIER_PHOTO,
    DocumentType.SUPPLIER_LICENSE,
    DocumentType.TAZKERA,
    DocumentType.PASSPORT,
    DocumentType.LICENSE,
    DocumentType.CUSTOMS,
    DocumentType.SALE_DOCUMENT,
    DocumentType.SUPPLIER_DOCUMENT,
]

FINANCING_DOC_TYPES = [
    DocumentType.FINANCE_AGREEMENT,
    DocumentType.GUARANTOR_DOCUMENT,
    DocumentType.TAZKERA,
    DocumentType.PASSPORT,
    DocumentType.OTHER_BILL,
    DocumentType.OTHER,
]


class Document(TenantModel, CompanyConsistencyMixin):
    company_relations = ("vehicle", "customer", "supplier", "finance_agreement")

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
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("supplier"),
        null=True,
        blank=True,
    )
    finance_agreement = models.ForeignKey(
        "financing.FinanceAgreement",
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("financing agreement"),
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
        constraints = [
            # Exactly one target, enforced at the database level (README §28):
            # shell scripts, imports and future code bypass form validation.
            models.CheckConstraint(
                condition=(
                    models.Q(vehicle__isnull=False, customer__isnull=True, supplier__isnull=True, finance_agreement__isnull=True)
                    | models.Q(vehicle__isnull=True, customer__isnull=False, supplier__isnull=True, finance_agreement__isnull=True)
                    | models.Q(vehicle__isnull=True, customer__isnull=True, supplier__isnull=False, finance_agreement__isnull=True)
                    | models.Q(vehicle__isnull=True, customer__isnull=True, supplier__isnull=True, finance_agreement__isnull=False)
                ),
                name="document_exactly_one_target",
            ),
        ]

    def __str__(self):
        return self.title or self.file.name

    @cached_property
    def file_exists(self):
        """Return whether storage still contains the referenced file.

        Database backups and Docker volumes have different lifecycles.  A
        restored database can therefore contain a valid ``FileField`` name
        after the corresponding media volume has been lost.  Templates use
        this property before rendering a URL so stale records degrade to a
        clear placeholder instead of a broken image or a 404 link.
        """
        if not self.file or not self.file.name:
            return False
        try:
            return self.file.storage.exists(self.file.name)
        except Exception:  # Storage outages must not break business pages.
            logger.warning(
                "Could not verify stored file for document %s",
                self.pk,
                exc_info=True,
            )
            return False

    @property
    def is_photo(self):
        return self.doc_type in (
            DocumentType.VEHICLE_PHOTO,
            DocumentType.CUSTOMER_PHOTO,
            DocumentType.SUPPLIER_PHOTO,
        )
