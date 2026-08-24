"""Management command: scan the database for integrity violations.

Read-only. Uses `all_objects` exclusively — a system audit must see across
tenants, and unrestricted access must always be explicit (§25.1). Exits 1
when violations are found so the command can gate deployments and CI runs.

Checks (mirrors the rules enforced by `CompanyConsistencyMixin` and the DB
constraints added in Phase 1, README §28):

- every `company_relations` target belongs to the same company;
- every Document has exactly one of vehicle/customer/supplier;
- at most one Invoice per Sale;
- at most one ACTIVE Reservation per Vehicle;
- at most one normal reversal per original LedgerEntry;
- positive amounts on Invoice, LedgerEntry, VehicleCostLine,
  PurchaseOrderLine.
"""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from apps.core.models import CompanyConsistencyMixin


class Command(BaseCommand):
    help = (
        "Scan for tenancy and financial-integrity violations across all "
        "companies (read-only)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            type=int,
            default=None,
            help="Restrict the audit to one company id.",
        )

    def handle(self, *args, **options):
        company_id = options["company"]
        checks = [
            ("same-company relations", self._check_same_company_relations),
            ("document targets", self._check_document_targets),
            ("invoices per sale", self._check_invoice_duplicates),
            ("active reservations per vehicle", self._check_active_reservations),
            ("reversals per ledger entry", self._check_reversal_duplicates),
            ("positive amounts", self._check_amounts),
        ]
        violations = []
        for label, check in checks:
            found = check(company_id)
            if found:
                violations.append((label, found))
        if violations:
            total = sum(len(items) for _label, items in violations)
            self.stderr.write(self.style.ERROR(f"{total} integrity violation(s) found:"))
            for label, items in violations:
                self.stderr.write(f"  [{label}]")
                for item in items:
                    self.stderr.write(f"    - {item}")
            raise CommandError(f"Integrity audit failed with {total} violation(s).")
        scope = f"company {company_id}" if company_id else "all companies"
        self.stdout.write(self.style.SUCCESS(f"Integrity audit passed for {scope}."))

    @staticmethod
    def _consistency_models():
        """Models that carry the `CompanyConsistencyMixin` validation."""
        for model in apps.get_models():
            if model._meta.abstract or model._meta.proxy:
                continue
            if not issubclass(model, CompanyConsistencyMixin):
                continue
            if model.company_relations:
                yield model

    def _scoped(self, qs, company_id):
        """Restrict an all_objects queryset to one company when requested."""
        if company_id is not None and "company" in {
            field.name for field in qs.model._meta.fields
        }:
            return qs.filter(company_id=company_id)
        return qs

    def _check_same_company_relations(self, company_id):
        violations = []
        for model in self._consistency_models():
            relation_fields = {
                field.name for field in model._meta.fields if field.is_relation
            }
            # GenericForeignKeys (e.g. LedgerEntry.related_object) are not
            # select_related-able; they are walked via getattr below.
            selectable = [
                attr for attr in model.company_relations if attr in relation_fields
            ]
            qs = model.all_objects.all()
            if selectable:
                qs = qs.select_related(*selectable)
            qs = self._scoped(qs, company_id)
            for obj in qs.iterator(chunk_size=500):
                for attr in model.company_relations:
                    related = getattr(obj, attr)
                    if related is None:
                        continue
                    related_company_id = getattr(related, "company_id", None)
                    if (
                        related_company_id is not None
                        and related_company_id != obj.company_id
                    ):
                        violations.append(
                            f"{model.__name__} #{obj.pk}: {attr} "
                            f"{related.__class__.__name__} #{related.pk} belongs "
                            f"to company {related_company_id}, expected {obj.company_id}"
                        )
        return violations

    def _check_document_targets(self, company_id):
        from apps.documents.models import Document

        target_fields = ("vehicle_id", "customer_id", "supplier_id")
        violations = []
        qs = self._scoped(Document.all_objects.all(), company_id)
        for doc in qs.iterator(chunk_size=500):
            targets = sum(1 for field in target_fields if getattr(doc, field) is not None)
            if targets != 1:
                violations.append(
                    f"Document #{doc.pk}: {targets} target(s), expected exactly one"
                )
        return violations

    def _check_invoice_duplicates(self, company_id):
        from apps.sales.models import Invoice

        qs = self._scoped(
            Invoice.all_objects.values("sale_id").annotate(n=Count("id")).filter(n__gt=1),
            company_id,
        )
        return [
            f"Sale #{row['sale_id']}: {row['n']} invoices, expected at most one"
            for row in qs
        ]

    def _check_active_reservations(self, company_id):
        from apps.sales.models import Reservation, ReservationStatus

        qs = self._scoped(
            Reservation.all_objects.filter(status=ReservationStatus.ACTIVE)
            .values("vehicle_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1),
            company_id,
        )
        return [
            f"Vehicle #{row['vehicle_id']}: {row['n']} ACTIVE reservations, "
            f"expected at most one"
            for row in qs
        ]

    def _check_reversal_duplicates(self, company_id):
        from apps.payments.models import LedgerEntry

        qs = self._scoped(
            LedgerEntry.all_objects.filter(reversal_of__isnull=False)
            .values("reversal_of_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1),
            company_id,
        )
        return [
            f"LedgerEntry #{row['reversal_of_id']}: {row['n']} reversals, "
            f"expected at most one"
            for row in qs
        ]

    def _check_amounts(self, company_id):
        from apps.payments.models import LedgerEntry
        from apps.purchases.models import PurchaseOrderLine, VehicleCostLine
        from apps.sales.models import Invoice

        violations = []
        for model in (Invoice, LedgerEntry, VehicleCostLine, PurchaseOrderLine):
            manager = getattr(model, "all_objects", model.objects)
            qs = self._scoped(manager.filter(amount__lte=0), company_id)
            for obj in qs.iterator(chunk_size=500):
                violations.append(
                    f"{model.__name__} #{obj.pk}: amount {obj.amount}, expected > 0"
                )
        return violations
