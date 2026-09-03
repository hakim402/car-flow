from django.db import migrations


class Migration(migrations.Migration):
    """Keep the completed-sale invariant in PostgreSQL without asking
    Django's ``full_clean`` to query through the fail-closed tenant manager.

    The service and model clean methods provide friendly validation, while
    the partial unique index created in 0007 remains the concurrency backstop.
    """

    dependencies = [
        ("sales", "0007_alter_historicalreservation_status_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="sale",
                    name="one_completed_sale_per_vehicle",
                ),
            ],
        ),
    ]
