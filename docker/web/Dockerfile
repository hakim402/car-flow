# syntax=docker/dockerfile:1
#
# Single image for web / worker / beat (docker-compose `command` selects the role).
# Multi-stage: builder installs deps, final stage is a slim runtime with no dev
# dependencies and a non-root user.

# ---------- builder: install Python dependencies ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev gettext \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python -m venv /opt/venv
COPY requirements/ ./requirements/
RUN pip install -r requirements/prod.txt

# ---------- dev: builder + test tooling (dev compose target only) ----------
FROM builder AS dev

RUN pip install -r requirements/dev.txt

# ---------- runtime: slim production image ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# gettext: runtime msgfmt support for compiled catalogs; libpq: psycopg runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 automex

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY . /app

# Windows checkouts may deliver CRLF; normalize the entrypoint and make sure
# it is executable (COPY from a Windows context does not preserve +x).
# Templates must be LF too: Django's template lexer splits tokens on \r, so
# multi-line {# #} comments in CRLF templates render as literal page text.
RUN sed -i 's/\r$//' /app/docker/entrypoint.sh && chmod +x /app/docker/entrypoint.sh \
    && find /app/templates -name '*.html' -exec sed -i 's/\r$//' {} +

# Compile translation catalogs at build time (never at container start).
RUN if ls locale/*/LC_MESSAGES/*.po >/dev/null 2>&1; then django-admin compilemessages; fi

# Collect static files at build time; Nginx serves them from the shared volume.
# Build-time placeholder secret only — a real SECRET_KEY comes from .env at runtime.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=build-time-placeholder-not-secret \
    DJANGO_ALLOWED_HOSTS='*' \
    python manage.py collectstatic --noinput

RUN mkdir -p /app/media && chown -R automex:automex /app

USER automex

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
