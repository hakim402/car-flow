import apps.core.models
import django.db.models.deletion
from django.db import migrations, models


def make_existing_receipts_unique(apps, schema_editor):
    LedgerEntry = apps.get_model("payments", "LedgerEntry")
    seen = set()
    for entry in LedgerEntry.objects.exclude(receipt_number="").order_by("company_id", "pk"):
        key = (entry.company_id, entry.receipt_number)
        if key not in seen:
            seen.add(key)
            continue
        suffix = f"-DUP-{entry.pk}"
        replacement = f"{entry.receipt_number[:100 - len(suffix)]}{suffix}"
        while (entry.company_id, replacement) in seen:
            replacement = f"{replacement[:90]}-{entry.pk}"
        LedgerEntry.objects.filter(pk=entry.pk).update(receipt_number=replacement)
        seen.add((entry.company_id, replacement))


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0001_initial"),
        ("payments", "0004_ledgerentry_branch_ledgerentry_expense_category_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="LedgerSequence",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("kind", models.CharField(max_length=30, verbose_name="sequence kind")),
                ("year", models.PositiveSmallIntegerField(verbose_name="year")),
                ("last_value", models.PositiveBigIntegerField(default=0, verbose_name="last value")),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="organizations.organization",
                        verbose_name="company",
                    ),
                ),
            ],
            options={
                "verbose_name": "ledger sequence",
                "verbose_name_plural": "ledger sequences",
            },
            bases=(apps.core.models.CompanyConsistencyMixin, models.Model),
        ),
        migrations.AddConstraint(
            model_name="ledgersequence",
            constraint=models.UniqueConstraint(
                fields=("company", "kind", "year"),
                name="unique_ledger_sequence_per_company_year",
            ),
        ),
        migrations.RunPython(make_existing_receipts_unique, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="ledgerentry",
            constraint=models.UniqueConstraint(
                condition=~models.Q(receipt_number=""),
                fields=("company", "receipt_number"),
                name="unique_receipt_number_per_company",
            ),
        ),
    ]
