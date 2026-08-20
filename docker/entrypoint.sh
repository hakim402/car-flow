#!/bin/sh
# Container entrypoint shared by web / worker / beat / runserver.
# Waits for the database; the web role applies migrations as an explicit
# logged step (workers must never migrate concurrently — concurrent
# `migrate` corrupts PostgreSQL state), then starts the role selected
# via the container `command`.
set -e

echo "==> Waiting for database at ${DB_HOST}:${DB_PORT:-5432}..."
until python - <<'PY' 2>/dev/null
import os
import psycopg

psycopg.connect(
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    host=os.environ["DB_HOST"],
    port=os.environ.get("DB_PORT", "5432"),
    connect_timeout=3,
).close()
PY
do
    sleep 1
done
echo "==> Database is ready."

ROLE="${1:-web}"
if [ "$ROLE" = "web" ] || [ "$ROLE" = "runserver" ]; then
    echo "==> Applying migrations..."
    python manage.py migrate --noinput
    echo "==> Migrations complete."
fi

case "$ROLE" in
    web)
        echo "==> Starting Gunicorn..."
        exec gunicorn config.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers "${GUNICORN_WORKERS:-3}" \
            --timeout "${GUNICORN_TIMEOUT:-60}"
        ;;
    runserver)
        echo "==> Starting Django dev server..."
        exec python manage.py runserver 0.0.0.0:8000
        ;;
    worker)
        echo "==> Starting Celery worker..."
        exec celery -A config worker --loglevel="${CELERY_LOG_LEVEL:-info}"
        ;;
    beat)
        echo "==> Starting Celery Beat..."
        exec celery -A config beat --loglevel="${CELERY_LOG_LEVEL:-info}"
        ;;
    *)
        exec "$@"
        ;;
esac
