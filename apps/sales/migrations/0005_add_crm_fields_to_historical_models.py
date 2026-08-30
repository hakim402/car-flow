from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0004_add_crm_fields_and_reservation_expiry"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="historicallead",
            name="assigned_to",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                help_text="Salesperson or team member handling follow-up.",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="assigned to",
            ),
        ),
        migrations.AddField(
            model_name="historicallead",
            name="lost_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("price_too_high", "Price too high"),
                    ("bought_elsewhere", "Bought elsewhere"),
                    ("no_response", "No response"),
                    ("financing", "Financing"),
                    ("vehicle_unavailable", "Vehicle unavailable"),
                    ("changed_mind", "Changed mind"),
                    ("other", "Other"),
                ],
                db_index=False,
                help_text="Reason the opportunity was closed as lost.",
                max_length=30,
                verbose_name="lost reason",
            ),
        ),
        migrations.AddField(
            model_name="historicalquotation",
            name="number",
            field=models.CharField(
                blank=True,
                help_text="Unique quotation reference, for example QT-2026-000123.",
                max_length=50,
                verbose_name="quotation number",
            ),
        ),
        migrations.AddField(
            model_name="historicalreservation",
            name="expires_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When this reservation expires and the stock is released automatically.",
                null=True,
                verbose_name="expires at",
            ),
        ),
    ]
