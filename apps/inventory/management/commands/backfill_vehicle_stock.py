from django.core.management.base import BaseCommand
from django.db import transaction

from apps.inventory.models import VehicleStock
from apps.vehicles.models import Vehicle


class Command(BaseCommand):
    help = "Create the authoritative inventory stock row for any vehicle missing one."

    @transaction.atomic
    def handle(self, *args, **options):
        created_count = 0
        skipped_count = 0

        for vehicle in Vehicle.all_objects.select_related("company", "branch").order_by("pk"):
            branch = vehicle.branch
            if branch is None:
                branch = vehicle.company.branches.order_by("pk").first() if vehicle.company_id else None
            if branch is None:
                skipped_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping vehicle {vehicle.pk} ({vehicle.vin}) — no branch available for stock row."
                    )
                )
                continue

            stock, created = VehicleStock.all_objects.get_or_create(
                vehicle=vehicle,
                defaults={
                    "company": vehicle.company,
                    "branch": branch,
                    "status": "received",
                },
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created stock for vehicle {vehicle.pk} ({vehicle.vin}) at {branch}."
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill complete: {created_count} stock rows created, {skipped_count} vehicles skipped."
            )
        )
