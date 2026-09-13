from django.db import migrations


FUNCTION_NAME = "carflow_prevent_immutable_financial_mutation"
TRIGGER_NAME = "payments_ledgerentry_immutable"


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE OR REPLACE FUNCTION {FUNCTION_NAME}()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'immutable financial rows cannot be updated or deleted';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        cursor.execute(
            f"""
            DROP TRIGGER IF EXISTS {TRIGGER_NAME} ON payments_ledgerentry;
            CREATE TRIGGER {TRIGGER_NAME}
            BEFORE UPDATE OR DELETE ON payments_ledgerentry
            FOR EACH ROW EXECUTE FUNCTION {FUNCTION_NAME}();
            """
        )


def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP TRIGGER IF EXISTS {TRIGGER_NAME} ON payments_ledgerentry;")


class Migration(migrations.Migration):
    dependencies = [("payments", "0006_alter_ledgerentry_type")]
    operations = [migrations.RunPython(create_trigger, drop_trigger)]
