from django.db import migrations


TABLES = (
    "financing_installment",
    "financing_paymentallocation",
    "financing_lenderdisbursement",
    "financing_agreementevent",
    "financing_installmentreminder",
)


def create_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            trigger = f"{table}_immutable"
            cursor.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table};")
            cursor.execute(
                f"""
                CREATE TRIGGER {trigger}
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION carflow_prevent_immutable_financial_mutation();
                """
            )


def drop_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table};")


class Migration(migrations.Migration):
    dependencies = [
        ("financing", "0001_initial"),
        ("payments", "0007_ledgerentry_database_immutability"),
    ]
    operations = [migrations.RunPython(create_triggers, drop_triggers)]
