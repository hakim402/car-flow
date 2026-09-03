import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0006_document_document_exactly_one_target"),
        ("financing", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="document",
            name="document_exactly_one_target",
        ),
        migrations.AddField(
            model_name="document",
            name="finance_agreement",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="documents",
                to="financing.financeagreement",
                verbose_name="financing agreement",
            ),
        ),
        migrations.AlterField(
            model_name="document",
            name="doc_type",
            field=models.CharField(
                choices=[
                    ("vehicle_photo", "Vehicle photo"),
                    ("license", "Vehicle license"),
                    ("sale_document", "Sale document"),
                    ("insurance", "Insurance policy"),
                    ("customs", "Customs / import document"),
                    ("inspection", "Inspection report"),
                    ("vehicle_document", "Other vehicle document"),
                    ("customer_photo", "Customer photo"),
                    ("tazkera", "Tazkera (national ID)"),
                    ("passport", "Passport"),
                    ("electricity_bill", "Electricity bill"),
                    ("other_bill", "Other bill"),
                    ("customer_document", "Other customer document"),
                    ("supplier_logo", "Supplier logo / photo"),
                    ("supplier_photo", "Supplier portrait photo"),
                    ("supplier_license", "Supplier business license"),
                    ("supplier_document", "Other supplier document"),
                    ("finance_agreement", "Signed financing agreement"),
                    ("guarantor_document", "Guarantor document"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=30,
                verbose_name="type",
            ),
        ),
        migrations.AddConstraint(
            model_name="document",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(vehicle__isnull=False, customer__isnull=True, supplier__isnull=True, finance_agreement__isnull=True)
                    | models.Q(vehicle__isnull=True, customer__isnull=False, supplier__isnull=True, finance_agreement__isnull=True)
                    | models.Q(vehicle__isnull=True, customer__isnull=True, supplier__isnull=False, finance_agreement__isnull=True)
                    | models.Q(vehicle__isnull=True, customer__isnull=True, supplier__isnull=True, finance_agreement__isnull=False)
                ),
                name="document_exactly_one_target",
            ),
        ),
    ]
