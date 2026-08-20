# AUTOMEX CarFlow

**Internal automotive ERP for multi-company car dealerships** — inventory,
purchasing, sales pipeline, payments on an append-only financial ledger,
document management, audit trails, and an omnichannel **Conversation Hub**
(WhatsApp · Messenger · Instagram · Telegram · Email · SMS).

| | |
|---|---|
| **Stack** | Python 3.12 · Django 5.2 LTS · PostgreSQL 16 · Redis 7 · Celery · Tailwind CSS · Docker |
| **Languages** | English · Dari (`prs`) · Pashto (`ps`) — full RTL support |
| **Deployment** | Single Docker image, three roles (web / worker / beat) behind Nginx |
| **Docs** | [`agent.md`](agent.md) (specification) · [`PRODUCTION.md`](PRODUCTION.md) (deployment) |

> Every external integration is toggleable. The entire system boots and runs
> with **zero providers configured** — disabled channels degrade to
> Null/console adapters automatically.

---

## Table of contents

1. [Feature overview](#feature-overview)
2. [Architecture](#architecture)
3. [Technology stack](#technology-stack)
4. [Repository layout](#repository-layout)
5. [Prerequisites](#prerequisites)
6. [Quick start](#quick-start)
7. [Users, companies, and roles](#users-companies-and-roles)
8. [Configuration reference (`.env`)](#configuration-reference-env)
9. [Everyday Docker commands](#everyday-docker-commands)
10. [Logging & observability](#logging--observability)
11. [Development workflow](#development-workflow)
12. [Testing](#testing)
13. [Internationalization (i18n)](#internationalization-i18n)
14. [Ports](#ports)
15. [Integrations overview](#integrations-overview)
16. [Backups](#backups)
17. [Deployment](#deployment)
18. [Security practices](#security-practices)
19. [Troubleshooting](#troubleshooting)

---

## Feature overview

| Domain | Capabilities |
|---|---|
| **Multi-tenancy** | Multiple companies, each with branches. Data isolation enforced at the ORM level (`TenantManager`) — cross-company reads are impossible through normal code paths; an explicit `all_objects` escape hatch exists for Super-Admin tooling only. |
| **Vehicles & inventory** | Vehicle registry (VIN unique per company), per-branch stock, lifecycle: in transit → in stock → reserved → sold → delivered. |
| **Purchasing** | Suppliers, purchase orders, receiving flow. Vehicle cost is **never stored on the vehicle** — it is computed from immutable `VehicleCostLine` rows. |
| **Sales pipeline** | Lead → Quotation → Reservation → Sale → Invoice. Completing a sale updates stock and notifies the customer automatically. |
| **Money** | Append-only ledger (`LedgerEntry`): rows are never updated or deleted; corrections are mirror rows with `reversal_of`. Balances and outstanding amounts are always computed aggregates — never stored columns. |
| **Audit** | `django-simple-history` tracks changes on business models (immutable financial rows are excluded by design). |
| **Conversation Hub** | One inbox per company across all channels. Unknown senders automatically become new customers (never silently merged). Raw provider payloads are persisted before parsing; webhook redelivery is deduplicated. |
| **Notifications** | Business code calls exactly one function — `notification_engine.notify(event, company, customer, context)` — which fans out over all of the customer's active channel identities. |
| **Documents** | Per-entity file uploads; storage backend switches between local `media/` volume and S3-compatible object storage via a single flag. |
| **i18n** | UI chrome in English / Dari / Pashto, per-user language preference, automatic RTL rendering for `prs` and `ps`. |
| **Access control** | Six seeded roles (Super Admin, Organization Admin, Branch Manager, Sales, Inventory, Accountant) plus custom roles/permissions as plain database rows. Django Admin restricted to Super Admin only. |

---

## Architecture

```
┌──────────────┐     ┌───────────────────────────────────────────────┐
│    Nginx     │────▶│  web        Gunicorn (prod) / runserver (dev) │
│ /static/     │     ├───────────────────────────────────────────────┤
│ /media/      │     │  worker     Celery — webhook processing       │
│ everything   │     ├───────────────────────────────────────────────┤
│ else proxied │     │  beat       Celery Beat — scheduled jobs      │
└──────────────┘     └────────┬──────────────────────────┬───────────┘
                              ▼                          ▼
                        PostgreSQL 16                  Redis 7
                        (all data)            (cache + Celery broker)
```

### One image, three roles

`web`, `worker`, and `beat` share the `automex-carflow` image; the container
`command` selects the role via `docker/entrypoint.sh`. The entrypoint waits
for the database, and **only the `web` role runs migrations** — concurrent
`migrate` from several containers corrupts PostgreSQL.

### Application map (`apps/`)

| App | Responsibility |
|---|---|
| `core` | Tenancy primitives (`TenantModel`/`TenantManager`), `ImmutableModel`, constants, shared factories for tests |
| `organizations` | Companies (tenants) |
| `branches` | Branches per company |
| `accounts` | Custom `User`, roles, permissions, login/dashboard |
| `vehicles` | Vehicle registry and lifecycle |
| `inventory` | Per-branch stock (`VehicleStock`) |
| `suppliers` | Supplier directory |
| `purchases` | Purchase orders, receiving, immutable `VehicleCostLine` |
| `customers` | Customer directory + channel identities |
| `sales` | Lead / Quotation / Reservation / Sale / Invoice pipeline |
| `payments` | The append-only **ledger** (`LedgerEntry`) |
| `expenses` | Expense capture (writes through the ledger) |
| `accounting` | Computed aggregates: balance, money in/out, sale outstanding |
| `audit` | `django-simple-history` wiring |
| `communications` | Conversation Hub: models, channel adapters, notification engine, webhooks |
| `documents` | File uploads with pluggable storage backend |

### Non-negotiable design rules (from `agent.md`)

1. **Fully Dockerized** — no host-level services required.
2. **Internal system behind login** — every page requires authentication.
3. **Trilingual + RTL** — `en` / `prs` / `ps`; direction driven by language.
4. **Toggleable integrations** — `*_ENABLED` flags; Null/console fallbacks;
   the app must boot with all flags off and empty credentials (enforced by tests).
5. **Append-only ledger** — financial rows are never updated or deleted.
6. **Business apps never import provider code** — only
   `notification_engine.notify(...)`; the adapter factory is the single place
   that reads integration flags.
7. **Explicit money** — every amount carries its currency.
8. **Multi-tenancy via `company_id`** — custom manager + middleware, never client input.
9. **Django Admin for Super Admin only.**

---

## Technology stack

| Layer | Technology |
|---|---|
| Language / framework | Python 3.12, Django 5.2 LTS |
| Frontend | Django Templates + Tailwind CSS 3.4 (compiled stylesheet committed) |
| Database | PostgreSQL 16 (containerized; pluggable to external) |
| Cache / broker | Redis 7 |
| Async tasks | Celery + Celery Beat |
| App server | Gunicorn (production), Django dev server (development) |
| Reverse proxy | Nginx 1.27 (static/media + proxy) |
| Audit | django-simple-history |
| Storage | django-storages[boto3] (optional S3), local `media/` volume by default |
| Tests | pytest + pytest-django + factory_boy |

---

## Repository layout

```
car-flow/
├── apps/                        # Django apps (one package per domain)
│   ├── core/                    # tenancy, immutability, test factories
│   ├── communications/          # Conversation Hub
│   ├── payments/                # append-only ledger
│   ├── accounting/              # computed aggregates
│   └── ...                      # (see architecture table)
├── config/
│   ├── settings/
│   │   ├── base.py              # shared settings + integration toggles
│   │   ├── dev.py               # development (DEBUG, eager Celery)
│   │   ├── test.py              # pytest (SQLite, all integrations off)
│   │   └── prod.py              # production (secure cookies, logging)
│   ├── urls.py                  # all app URLs + /webhooks/meta/
│   ├── celery.py                # Celery app
│   └── checks.py                # toggle-validation system checks
├── docker/
│   ├── web/Dockerfile           # multi-stage: builder / dev / runtime
│   ├── entrypoint.sh            # DB wait + migrate (web only) + role start
│   └── nginx/nginx.conf         # static/media serving + proxy
├── locale/{en,prs,ps}/          # translation catalogs (.po sources)
├── requirements/                # base / dev / prod dependency sets
├── scripts/                     # helper scripts
├── static/, templates/          # global assets + base templates
├── docker-compose.yml           # production stack
├── docker-compose.override.yml  # dev overrides (applied automatically)
├── .env.example                 # template for your local .env
├── pytest.ini                   # test configuration
├── README.md / PRODUCTION.md    # documentation
└── agent.md                     # authoritative build specification
```

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Docker Desktop** with Compose plugin | Docker Engine ≥ 24, Compose ≥ 2.20. |
| **WSL 2** *(Windows only)* | `wsl --install` as administrator → reboot → enable the WSL backend in Docker Desktop settings. |
| **Git** | For cloning the repository. |
| **Free host port** | Default **8765** ([changeable](#ports)). |

Python, Node.js, PostgreSQL and Redis are **not** required on the host —
everything runs in containers. (Optional host tooling: Python + venv for
faster test loops, Node for Tailwind rebuilds.)

---

## Quick start

Works identically on Windows (PowerShell), macOS and Linux.

```bash
# 1. Clone
git clone https://github.com/hakim402/car-flow.git
cd car-flow

# 2. Create your environment file
cp .env.example .env                  # PowerShell: Copy-Item .env.example .env

# 3. Edit .env — minimum changes:
#    • DJANGO_SECRET_KEY  → long random value
#      (generate: docker run --rm python:3.12-slim python -c "import secrets;print(secrets.token_urlsafe(50))")
#    • DB_PASSWORD        → a private password
#    • leave every *_ENABLED flag False and every credential blank

# 4. Build and start (first build takes several minutes)
docker compose up --build

# 5. Verify
#    http://localhost:8765           → redirects to the login page
```

`docker compose up` automatically applies `docker-compose.override.yml`
(development mode: source bind-mounted, Django dev server with auto-reload,
DEBUG on, Nginx dormant). Migrations run automatically in the `web`
container on every start.

Sanity check from a terminal:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8765/accounts/login/
# → 200
```

---

## Users, companies, and roles

Everything sits behind login. Roles are seeded by migrations.

### Step 1 — create a Super Admin

The only role allowed into Django Admin (`/admin/`):

```bash
docker compose exec web python manage.py createsuperuser
```

### Step 2 — create a company and staff via Admin

Log in at `http://localhost:8765/admin/` and create, in order:

1. **Organization** — a company/tenant.
2. **Branch** *(optional)* — belongs to the organization.
3. **User** — assign `company` (required), optionally `branch`, one or more
   `roles`, and a `preferred_language` (`en` / `prs` / `ps`).

> A Super Admin has no company. Every regular user belongs to exactly one
> company — that company is the tenant all their data is scoped to.

### Alternative — create a company + org admin from the shell

```bash
docker compose exec web python manage.py shell
```

```python
from apps.organizations.models import Organization
from apps.accounts.models import Role, User

org = Organization.objects.create(name="AUTOMEX Kabul")
user = User.objects.create_user(
    username="manager", password="change-me-strong", company=org,
)
user.roles.add(Role.objects.get(key="org_admin"))
user.save()   # re-save keeps is_staff in sync with the role set
```

### Seeded roles

| Key | Purpose |
|---|---|
| `super_admin` | Platform owner; sole Admin access; no company |
| `org_admin` | Runs a company (branches, users, all data) |
| `branch_manager` | Manages one branch |
| `sales` | Pipeline and payments |
| `inventory` | Vehicles, stock, receiving |
| `accountant` | Payments, expenses, accounting |

Custom roles and granular permissions are plain database rows — see
[`PRODUCTION.md` §5](PRODUCTION.md#5-users-companies-branches-roles).

### Password resets

```bash
docker compose exec web python manage.py changepassword <username>
```

### Resetting the whole environment

```bash
docker compose down -v     # stops containers AND deletes DB/media volumes
docker compose up --build  # fresh, migrated database
```

> ⚠️ `-v` wipes the database. Never use it against production.

---

## Configuration reference (`.env`)

All configuration is environment-driven. The full documented template is
[`.env.example`](.env.example).

### Core

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | — | **Required.** Long random secret for signing. |
| `DJANGO_DEBUG` | `False` | Never `True` outside local development. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hostnames served. |
| `DJANGO_SETTINGS_MODULE` | set by compose | `dev` / `test` / `prod` — usually untouched. |

### Database & Redis

| Variable | Default | Description |
|---|---|---|
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | `carflow`/`carflow`/— | Used by the app **and** the `db` container. |
| `DB_HOST` / `DB_PORT` | `db` / `5432` | Point elsewhere for an external PostgreSQL. |
| `REDIS_URL` | `redis://redis:6379/0` | Django cache + Celery broker/backend. |

### Ports & servers

| Variable | Default | Description |
|---|---|---|
| `NGINX_PORT` | `8765` | Host port mapped to Nginx (production). |
| `DEV_PORT` | `8765` | Host port mapped to the dev server (development). |
| `GUNICORN_WORKERS` | `3` | Gunicorn worker processes (production). |
| `GUNICORN_TIMEOUT` | `60` | Worker timeout in seconds. |

### Security

| Variable | Default | Description |
|---|---|---|
| `COOKIES_SECURE` | `True` | HTTPS-only session/CSRF cookies. Set `False` **only** for plain-HTTP deployments, or every form POST fails with a CSRF 403. |

### Integration toggles

Every provider follows the same pattern: one `*_ENABLED` master flag plus
credential variables. When the flag is `False`, credentials may be blank and
the system uses Null/console adapters.

| Provider | Flag | Credentials |
|---|---|---|
| WhatsApp / Messenger / Instagram | `META_ENABLED` | `META_APP_ID`, `META_APP_SECRET`, `META_ACCESS_TOKEN`, `META_WEBHOOK_VERIFY_TOKEN`, `META_WHATSAPP_PHONE_NUMBER_ID`, `META_MESSENGER_PAGE_ID`, `META_INSTAGRAM_PAGE_ID` |
| Telegram | `TELEGRAM_ENABLED` | `TELEGRAM_BOT_TOKEN` *(adapter arrives in Phase 2)* |
| SMS | `SMS_ENABLED` | `SMS_GATEWAY_URL`, `SMS_GATEWAY_API_KEY` |
| Email | `EMAIL_ENABLED` | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` |
| S3 storage | `S3_ENABLED` | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_NAME` |

**Contract:** the app must boot with every flag `False` and every credential
blank — this is enforced by the test suite.

---

## Everyday Docker commands

All commands run from the repository root.

### Service lifecycle

| Task | Command |
|---|---|
| Start (foreground logs, Ctrl+C stops) | `docker compose up` |
| Start detached | `docker compose up -d` |
| Build images (after dependency/Dockerfile changes) | `docker compose build` |
| Build + (re)start detached | `docker compose up -d --build` |
| Restart one service | `docker compose restart web` |
| Force-recreate a container (env changed) | `docker compose up -d --force-recreate web` |
| Stop (keeps data) | `docker compose down` |
| Stop **and delete data** | `docker compose down -v` |
| Service status / ports | `docker compose ps` |
| List images | `docker images automex-carflow` |
| Disk usage | `docker system df` |

> Add `-f docker-compose.yml` to any command to target the **production**
> stack explicitly (skips the dev override), e.g.
> `docker compose -f docker-compose.yml ps`.

### Application access

| Task | Command |
|---|---|
| Django shell | `docker compose exec web python manage.py shell` |
| Database shell (psql) | `docker compose exec db psql -U carflow -d carflow` |
| Redis CLI | `docker compose exec redis redis-cli` |
| Shell inside the app container | `docker compose exec web sh` |
| One-off command in a **fresh** container | `docker compose run --rm web <cmd>` |

### Django management

| Task | Command |
|---|---|
| Run migrations manually | `docker compose exec web python manage.py migrate` |
| Show migration state | `docker compose exec web python manage.py showmigrations` |
| Create migrations after model edits | `docker compose exec web python manage.py makemigrations <app>` |
| System checks | `docker compose exec web python manage.py check` |
| Create Super Admin | `docker compose exec web python manage.py createsuperuser` |
| Change password | `docker compose exec web python manage.py changepassword <user>` |
| Show URLs | `docker compose exec web python manage.py show_urls` *(if installed)* or read `config/urls.py` |
| Collect static files | done at image build time; rebuild the image if needed |

---

## Logging & observability

### Reading logs

| What | Command |
|---|---|
| **All services, live** | `docker compose logs -f` |
| One service, live | `docker compose logs -f web` |
| Several services | `docker compose logs -f web worker` |
| Last N lines | `docker compose logs --tail 100 web` |
| Since a time window | `docker compose logs --since 30m web` |
| With timestamps | `docker compose logs -f -t web` |
| Plain docker (container name) | `docker logs -f automex-car-flow-web-1` |

Container names follow `automex-car-flow-<service>-1`: `web`, `worker`,
`beat`, `db`, `redis` (add `-f docker-compose.yml` for the prod stack).

### What to look for per service

| Service | Healthy log signature |
|---|---|
| `web` | `==> Migrations complete.` then `Starting Gunicorn...` / `Starting Django dev server...` |
| `worker` | `celery@<host> ready.` and `Connected to redis://redis:6379/0` |
| `beat` | `beat: Starting...` |
| `db` | `database system is ready to accept connections` |

### Log levels

Production logging is configured in `config/settings/prod.py`
(console handler, structured single-line format). Adjust via env when
starting the stack, e.g. `DJANGO_LOG_LEVEL=DEBUG` in `.env`, then
`docker compose up -d --force-recreate web`. Celery verbosity:
`CELERY_LOG_LEVEL=debug`.

### Saving logs to a file

```bash
docker compose logs --no-color web > web.log          # snapshot
docker compose logs -f web 2>&1 | Tee-Object -FilePath web.log   # live (PowerShell)
docker compose logs -f web 2>&1 | tee web.log                    # bash
```

### Health checks

```bash
docker compose ps                          # db / redis show (healthy)
docker compose ps --format "{{.Name}}: {{.Status}}"
curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/accounts/login/
```

### Live inspection / debugging

```bash
docker compose exec web python manage.py shell          # ORM queries
docker compose exec db psql -U carflow -d carflow \
  -c "select count(*) from payments_ledgerentry;"       # direct DB look
docker stats                                            # CPU/RAM per container
docker compose exec web sh -c "ls /app/media"           # inspect volumes
```

### Webhook traffic

Meta webhook endpoint: `/webhooks/meta/`.
- Returns **503** while `META_ENABLED=False` (expected in dev).
- Inbound payloads are stored verbatim on `Message.raw_payload` before
  parsing — inspect them via the Conversations UI or the DB.

---

## Development workflow

### Editing code

- **Python/templates:** the dev stack bind-mounts the source; the dev server
  auto-reloads on save. Settings changes also trigger a reload.
- **Dependencies (`requirements/*.txt`):** rebuild →
  `docker compose build web && docker compose up -d`.
- **Dockerfile / entrypoint:** `docker compose up -d --build`.
- **New app:** create the package under `apps/`, add it to
  `INSTALLED_APPS` in `config/settings/base.py`, run `makemigrations <app>`.

### Model → migration loop

```bash
docker compose exec web python manage.py makemigrations <app>
docker compose exec web python manage.py migrate
docker compose exec web python manage.py check
```

Commit migration files together with the model changes.

### Static files & Tailwind

The compiled stylesheet is committed (`static/css/tailwind.css`), so ordinary
Docker development needs **no Node**. After adding new Tailwind classes to
templates, rebuild the stylesheet on the host:

```bash
npx tailwindcss@3.4.17 -i static/css/src.css -o static/css/tailwind.css --minify
```

In production, static files are collected at image **build time** and served
by Nginx from the `static_files` volume.

### Code conventions (short version)

- All user-facing strings wrapped in `{% translate "…" %}` / `gettext_lazy`.
- Money always as `amount + currency` (Decimal, never float).
- Tenant-scoped models inherit `TenantModel`; never filter by client input.
- Financial rows inherit `ImmutableModel`; corrections are reversal rows.
- Business apps call `notification_engine.notify(...)` — never providers.
- Tailwind logical properties only (`ms-*`, `text-start`) for RTL safety.

---

## Testing

The mandatory test gates (ledger immutability, tenant isolation,
integrations-off boot) live in `apps/*/tests/`.

```bash
# In the container — identical environment to production
docker compose run --rm web pytest
docker compose run --rm web pytest -q apps/payments          # one app
docker compose run --rm web pytest -k test_reversal          # by name

# On the host (SQLite, no services needed)
python -m venv .venv
.venv\Scripts\pip install -r requirements/dev.txt    # Windows
.venv\Scripts\python -m pytest                       # Windows
# macOS/Linux: .venv/bin/pip ... && .venv/bin/python -m pytest
```

The suite runs under `config/settings/test.py`: SQLite, eager Celery, and
**every `*_ENABLED` flag off with empty credentials** — the suite itself is
the integrations-off boot gate.

---

## Internationalization (i18n)

Languages: `en` (English), `prs` (Dari, RTL), `ps` (Pashto, RTL).
`prs` and `ps` render `dir="rtl"` automatically; users choose their language
from the header dropdown (stored in a cookie) or via `User.preferred_language`.

Workflow after adding/changing strings:

```bash
# 1. Extract into locale/{en,prs,ps}/LC_MESSAGES/django.po
docker compose run --rm web python manage.py makemessages -l en -l prs -l ps

# 2. Fill in the msgstr entries for prs / ps

# 3. Compile to binary .mo catalogs
docker compose run --rm web python manage.py compilemessages

# 4. Reload the page (dev) — the production image compiles at build time
```

Hosts without GNU gettext can regenerate catalogs with
`python scripts/extract_messages.py`, but `makemessages` in Docker is the
canonical flow.

Quick RTL check: set cookie `django_language=prs` and reload any page —
`<html lang="prs" dir="rtl">` must appear.

---

## Ports

Both modes use host port **8765** by default:

| Mode | Variable | Mapping |
|---|---|---|
| Development | `DEV_PORT` | `${DEV_PORT:-8765}` → Django dev server `8000` |
| Production | `NGINX_PORT` | `${NGINX_PORT:-8765}` → Nginx `80` |

Change in `.env`, then `docker compose up -d`. Container-internal ports stay
fixed — only the host mapping changes.

---

## Integrations overview

- **Inbound:** provider webhooks hit `/webhooks/<provider>/` → signature
  verification → raw payload enqueued → `200` returned immediately. The
  worker parses, deduplicates on external message IDs, resolves the customer
  (§7.4: unknown sender ⇒ new customer, never silent merge), and stores the
  message in the Conversation Hub.
- **Outbound:** business events (`payment_recorded`, `sale_completed`, …)
  call `notification_engine.notify(...)`; the engine resolves the customer's
  active channel identities and sends through each channel's adapter.
- **Disabled channels:** outbound attempts are persisted with status
  `skipped_disabled`; inbound endpoints refuse with `503`. Nothing crashes,
  nothing is lost.

Enabling providers, Meta webhook configuration, and per-channel credentials:
[`PRODUCTION.md` §8](PRODUCTION.md#8-enabling-integrations-when-ready).

---

## Backups

```bash
# Database dump (timestamped)
docker compose exec -T db pg_dump -U carflow -d carflow > backup_$(date +%F).sql

# Restore
docker compose exec -T db psql -U carflow -d carflow < backup_2026-08-20.sql
```

Media lives in the `media_data` volume — snapshot it alongside the dump when
using local storage. Full backup/restore procedures:
[`PRODUCTION.md` §4c](PRODUCTION.md#4c-backups--restore).

---

## Deployment

Production deployment (TLS, external PostgreSQL, roles, operations) is
covered end-to-end in **[`PRODUCTION.md`](PRODUCTION.md)**:

1. [Production architecture](PRODUCTION.md#1-production-architecture)
2. [Server prerequisites](PRODUCTION.md#2-server-prerequisites)
3. [First deployment](PRODUCTION.md#3-first-deployment)
4. [PostgreSQL (containerized & external)](PRODUCTION.md#4-postgresql)
5. [Users, companies, branches, roles](PRODUCTION.md#5-users-companies-branches-roles)
6. [Nginx configuration](PRODUCTION.md#6-nginx-in-this-stack)
7. [HTTPS / TLS termination](PRODUCTION.md#7-https--tls-termination)
8. [Enabling integrations](PRODUCTION.md#8-enabling-integrations-when-ready)
9. [Updates, rollbacks, operations](PRODUCTION.md#9-updates-rollbacks-operations)
10. [Security checklist](PRODUCTION.md#10-security-checklist)

---

## Security practices

- **Login everywhere.** No public endpoint except provider webhooks (which
  verify signatures and refuse while disabled).
- **Tenant isolation** at the ORM layer; bulk operations through the default
  manager only ever touch the current tenant.
- **Append-only money.** Ledger rows cannot be updated or deleted at the
  model level; corrections are signed reversal rows.
- **Secure cookies** in production (`COOKIES_SECURE=True` default),
  `X-Frame-Options: DENY`, content-type nosniff.
- **Secrets only in `.env`** (git-ignored); `.env.example` ships no secrets.
- **Least privilege:** Django Admin for Super Admin only; granular
  permission codenames per role.
- **No provider secrets in code** — all credentials are env-driven.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `The Windows Subsystem for Linux is not installed` | `wsl --install` as administrator → reboot → restart Docker Desktop. |
| `port is already allocated` on `up` | Change `DEV_PORT`/`NGINX_PORT` in `.env`, or stop the conflicting service. |
| `403 CSRF verification failed` on form POST | Plain-HTTP stack with Secure cookies: set `COOKIES_SECURE=False` in `.env`, then `docker compose up -d --force-recreate web` (add `-f docker-compose.yml` for the prod stack). HTTPS deployments keep it `True`. |
| `IntegrityError … pg_type_typname_nsp_index` on first boot | Corrupted first-migration state: `docker compose down -v` then `docker compose up`. (Prevented structurally: only the web service migrates.) |
| `pytest: not found` in the container | The last build tagged the runtime (prod) image. Rebuild dev: `docker compose build web`. |
| Changes don't appear | Dev auto-reloads Python/templates; for `.env` changes use `up -d --force-recreate`; for dependency/Dockerfile changes use `up -d --build`. |
| Static files missing in prod stack | They're collected at build time — rebuild: `docker compose -f docker-compose.yml build`. |
| Blank/untranslated UI in Dari/Pashto | Check the `django_language` cookie / user preference and that `.mo` catalogs are compiled. |
| Webhook returns 503 | Expected while the provider's `*_ENABLED` flag is `False`. |
| Outbound messages show `skipped_disabled` | Same cause — the channel's integration is off by design (§12). |
| Container restarts in a loop | Check `docker compose logs <service>`; usually DB wait or a missing env var. |
| Slow first build | Base packages are downloaded once; later builds reuse the layer cache. |

---

## License & support

Internal project of AUTOMEX. For the complete product and architecture
specification see [`agent.md`](agent.md); for deployment runbooks see
[`PRODUCTION.md`](PRODUCTION.md).
