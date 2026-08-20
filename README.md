# AUTOMEX CarFlow

AUTOMEX CarFlow is an internal automotive ERP for multi-company car dealerships:
inventory, purchasing, sales pipeline, payments on an append-only financial
ledger, document management, and an omnichannel **Conversation Hub**
(WhatsApp / Messenger / Instagram / Telegram / Email / SMS).

The system is **fully Dockerized**, **trilingual** (English, Dari `prs`,
Pashto `ps`) with full **RTL** support, and designed so that **every external
integration can be switched off** — the whole product boots and runs with zero
providers configured.

> The authoritative build specification is [`agent.md`](agent.md).

---

## Feature overview

| Area | What you get |
|---|---|
| Multi-tenancy | Multiple companies, each with branches. All data is isolated per company at the ORM level (`TenantManager`) — cross-company reads are impossible through normal code paths. |
| Vehicles & inventory | Vehicle registry (VIN unique per company), per-branch stock, status flow: in transit → in stock → reserved → sold → delivered. |
| Purchasing | Suppliers, purchase orders, receiving flow. Vehicle cost is **never stored on the vehicle** — it is computed from immutable `VehicleCostLine` rows. |
| Sales pipeline | Lead → Quotation → Reservation → Sale → Invoice. Completing a sale updates stock and notifies the customer. |
| Money | Append-only ledger (`LedgerEntry`): rows are never updated or deleted; corrections are mirror rows with `reversal_of`. Balances and outstanding amounts are always computed aggregates. |
| Audit | `django-simple-history` tracks changes on business models (immutable financial rows are excluded by design). |
| Conversation Hub | One inbox per company across all channels. Unknown senders automatically become new customers (never silently merged). Raw provider payloads are stored before parsing. |
| Notifications | Business code calls exactly one function: `notification_engine.notify(event, company, customer, context)` — it fans out over the customer's active channels. |
| Documents | Per-vehicle/customer file uploads; storage backend switches between local `media/` volume and S3 via `S3_ENABLED`. |
| i18n | UI chrome in English / Dari / Pashto, per-user language preference, automatic RTL for `prs` and `ps`. |

---

## Tech stack

- **Python 3.12 / Django 5.2 LTS**, Django Templates + **Tailwind CSS 3.4**
- **PostgreSQL 16** (data), **Redis 7** (cache + Celery broker)
- **Celery + Beat** (async webhook processing, future scheduled jobs)
- **Gunicorn** behind **Nginx** in production
- **pytest + pytest-django + factory_boy** for the mandatory test gates
- **docker-simple-history**, **django-storages[boto3]**

---

## Architecture at a glance

```
┌────────────┐   ┌────────────────────────────────────────────┐
│   Nginx    │──▶│  web (Gunicorn / runserver in dev)         │
│ static+media│   ├────────────────────────────────────────────┤
└────────────┘   │  worker (Celery)     beat (Celery Beat)    │
                 └──────────┬──────────────────────┬───────────┘
                            ▼                      ▼
                       PostgreSQL                Redis
```

- **One image, three roles.** `web`, `worker`, `beat` share the
  `automex-carflow` image; the entrypoint selects the role via the compose
  `command`. Only the `web` role runs migrations (workers must never migrate
  concurrently).
- **Apps** live in `apps/`: `core` (tenancy, immutability), `organizations`,
  `branches`, `accounts`, `vehicles`, `inventory`, `suppliers`, `purchases`,
  `customers`, `sales`, `payments` (ledger), `expenses`, `accounting`
  (computed aggregates), `audit`, `communications` (Conversation Hub),
  `documents`.
- **Provider isolation.** Business apps never import provider code. The only
  sanctioned path is `apps.communications.notification_engine.notify(...)`.
  The adapter factory (`get_channel_adapter`) is the single place that reads
  the `*_ENABLED` flags; disabled channels degrade to a `NullChannelAdapter`.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Docker Desktop** with the Compose plugin | On Windows, WSL 2 must be installed (`wsl --install`, then reboot) and the WSL backend enabled in Docker Desktop. |
| **Git** | For cloning the repository. |
| **Ports** | `8765` free on the host (see [Changing the port](#changing-the-port)). |

That's it — Python, Node, PostgreSQL and Redis are **not** required on the
host for Docker-based development.

---

## Setting up on a new computer

```bash
# 1. Clone
git clone https://github.com/hakim402/car-flow.git
cd car-flow

# 2. Create your local environment file
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env

# 3. Edit .env (mandatory!)
#    - set a long random DJANGO_SECRET_KEY
#    - change DB_PASSWORD to something private
#    - leave every *_ENABLED flag False and every credential blank for now

# 4. Build and start (first build takes several minutes)
docker compose up --build

# 5. Open the app
#    http://localhost:8765  →  redirects to the login page
```

`docker compose up` automatically applies `docker-compose.override.yml`
(development mode: source bind-mounted, Django dev server, DEBUG on, Nginx
dormant). Migrations run automatically in the `web` container on start.

### Creating your first user

The app is internal-only — everything sits behind login. Roles are seeded by
migrations (Super Admin, Organization Admin, Branch Manager, Sales,
Inventory, Accountant).

**Step 1 — create a Super Admin** (the only role allowed into `/admin/`):

```bash
docker compose exec web python manage.py createsuperuser
```

**Step 2 — log in at** `http://localhost:8765/admin/` **and create:**

1. an **Organization** (a company/tenant),
2. a **Branch** (optional, belongs to the organization),
3. **Users** — assign `company`, optionally `branch`, and one or more `roles`.

> A Super Admin user has no company. Every regular user must belong to
> exactly one company — that company is the tenant all their data is
> scoped to.

**Alternative (shell) — create a company + org admin in one go:**

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
user.save()          # re-save syncs is_staff with the role set
```

### Resetting everything

```bash
docker compose down -v    # stops containers AND deletes database/media volumes
docker compose up --build # starts from a clean, migrated database
```

> `-v` is destructive: it wipes the dev database. Never use it in production.

---

## Everyday Docker commands

All commands run from the repository root.

| Task | Command |
|---|---|
| Start the stack (foreground logs) | `docker compose up` |
| Start detached | `docker compose up -d` |
| Stop the stack (keeps data) | `docker compose down` |
| Stop + delete data volumes | `docker compose down -v` |
| Follow logs | `docker compose logs -f` |
| Logs of one service | `docker compose logs -f web` |
| Service status | `docker compose ps` |
| Rebuild after dependency changes | `docker compose build` then `docker compose up -d` |
| Django shell | `docker compose exec web python manage.py shell` |
| Database shell | `docker compose exec db psql -U carflow -d carflow` |
| Run migrations manually | `docker compose exec web python manage.py migrate` |
| Make migrations after model edits | `docker compose exec web python manage.py makemigrations <app>` |
| Create a Super Admin | `docker compose exec web python manage.py createsuperuser` |
| Change a user's password | `docker compose exec web python manage.py changepassword <username>` |
| Run a one-off command in a fresh container | `docker compose run --rm web <cmd>` |

> The default DB user/database in `.env.example` is `carflow`/`carflow`.
> If you changed `DB_USER`/`DB_NAME` in `.env`, use those values with `psql`.

### Running tests

```bash
# In the container (recommended — identical environment to CI/prod)
docker compose run --rm web pytest

# Or on the host with a local virtualenv (uses SQLite, no services needed)
python -m venv .venv
.venv\Scripts\pip install -r requirements/dev.txt   # Windows
.venv/Scripts/pip install -r requirements/dev.txt   # macOS/Linux
.venv\Scripts\python -m pytest                      # Windows
.venv/Scripts/python -m pytest                      # macOS/Linux
```

The test settings (`config/settings/test.py`) run with **every integration
flag off and every credential empty** — the suite itself is the
"integrations-off boot" gate required by the spec.

### Translation (i18n) workflow

Strings are marked with `{% translate "..." %}` in templates and
`gettext_lazy("...")` in Python.

```bash
# 1. Extract new strings into locale/{en,prs,ps}/LC_MESSAGES/django.po
docker compose run --rm web python manage.py makemessages -l en -l prs -l ps

# 2. Translate the empty msgstr entries in the .po files (prs = Dari, ps = Pashto)

# 3. Compile to .mo (the production image also does this at build time)
docker compose run --rm web python manage.py compilemessages

# 4. Restart / reload to see changes
```

On hosts without GNU gettext you can regenerate the catalogs with
`python scripts/extract_messages.py` (pure-Python fallback), but
`makemessages` inside Docker is the canonical flow.

Language switching: authenticated users pick their language from the header
dropdown (stored in a session cookie). For quick checks you can also set the
`django_language=prs|ps|en` cookie manually.

### Tailwind CSS

The compiled stylesheet is committed (`static/css/tailwind.css`), so day-to-day
Docker development needs no Node. After editing templates with new Tailwind
classes, rebuild it on the host:

```bash
npx tailwindcss@3.4.17 -i static/css/src.css -o static/css/tailwind.css --minify
```

---

## Changing the port

Both modes use host port **8765** by default:

- **Development:** `DEV_PORT` → mapped to the Django dev server
  (`docker-compose.override.yml`).
- **Production:** `NGINX_PORT` → mapped to Nginx (`docker-compose.yml`).

To use another port, edit `.env`:

```dotenv
DEV_PORT=9000
NGINX_PORT=9000
```

then `docker compose up -d`. Container-internal ports stay fixed (8000 for
Django/Gunicorn, 80 for Nginx) — only the host mapping changes.

---

## Environment variables

All configuration is env-driven (`.env`). The most important groups:

| Group | Variables | Meaning |
|---|---|---|
| Core | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | Django basics. Keep `DEBUG=False` outside local dev. |
| Database | `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Used by both the app and the `db` container. |
| Redis | `REDIS_URL` | Cache + Celery broker (`redis://redis:6379/0`). |
| Ports | `NGINX_PORT`, `DEV_PORT` | Host port mappings. |
| Meta (WhatsApp/Messenger/Instagram) | `META_ENABLED`, `META_APP_ID`, `META_APP_SECRET`, `META_ACCESS_TOKEN`, `META_WEBHOOK_VERIFY_TOKEN`, … | Off by default → Null adapter. |
| Telegram / SMS / Email | `TELEGRAM_ENABLED`, `SMS_ENABLED`, `EMAIL_ENABLED`, … | Off by default. |
| Storage | `S3_ENABLED`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_NAME` | Off → files go to the local `media/` volume. |

**Contract:** the app must boot with every `*_ENABLED=False` and every
credential blank — this is enforced by the test suite.

---

## Project layout

```
├── apps/                    # Django apps (one package per business domain)
│   ├── core/                # tenancy, ImmutableModel, factories for tests
│   ├── communications/      # Conversation Hub: models, adapters, engine, webhooks
│   ├── payments/            # append-only ledger
│   ├── accounting/          # computed aggregates (balance, money in/out)
│   └── ...
├── config/                  # Django project: settings (base/dev/test/prod), urls, celery
├── docker/                  # Dockerfile, entrypoint.sh, nginx config
├── locale/{en,prs,ps}/      # translation catalogs (.po sources; .mo built in image)
├── requirements/            # base / dev / prod dependency sets
├── scripts/                 # helper scripts (message extraction, toggle gate)
├── static/, templates/      # global assets and base templates
├── docker-compose.yml       # production stack
├── docker-compose.override.yml  # dev overrides (auto-applied)
├── .env.example             # template for your local .env
└── agent.md                 # authoritative build specification
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `The Windows Subsystem for Linux is not installed` | `wsl --install` as administrator, reboot, restart Docker Desktop. |
| Port already in use on `up` | Change `DEV_PORT`/`NGINX_PORT` in `.env`, or stop the other service. |
| `IntegrityError ... pg_type_typname_nsp_index` on first boot | Corrupted first-migration state: `docker compose down -v`, then `docker compose up`. (Already prevented: only the web service migrates.) |
| Changes to Python files don't appear | Dev auto-reloads; for settings changes or new deps: `docker compose up -d --build`. |
| `pytest: not found` in a container | The last build tagged the production (runtime) image. Rebuild dev: `docker compose build web`. |
| Static files missing in production stack | The image collects them at build time; rebuild: `docker compose -f docker-compose.yml build`. |
| Blank/untranslated UI in Dari/Pashto | Check the `django_language` cookie / user preference, and that `.mo` catalogs are compiled. |
| `403 CSRF verification failed` on form POST (prod stack) | You're serving plain HTTP but cookies are Secure. Set `COOKIES_SECURE=False` in `.env`, then `docker compose -f docker-compose.yml up -d --force-recreate web`. (HTTPS deployments keep it True.) |

---

## Further reading

- **Deployment, HTTPS, roles, PostgreSQL management** → [`PRODUCTION.md`](PRODUCTION.md)
- **Full product & architecture specification** → [`agent.md`](agent.md)
