# AGENT.md — AUTOMEX CarFlow Build Instructions

This file is the source of truth for the coding agent building **AUTOMEX CarFlow**, an AI-powered automotive ERP with an omnichannel communications layer. Read this file fully before writing any code. Follow the phases and steps **in order** — do not skip ahead to later-phase features (AI layer, extra channels) before earlier phases are complete and working.

---

## 1. Project Summary

AUTOMEX CarFlow is a multi-company, multi-branch ERP for automotive dealers, covering vehicle inventory, purchasing, sales, CRM, and finance — unified with a two-way messaging layer (WhatsApp, Messenger, Instagram, Telegram, Email, SMS) called the **Conversation Hub**, and an AI layer added last.

Non-negotiable principles for every phase:

- **The app must be fully Dockerized.** No component runs "on the host" — web, worker, beat scheduler, database, cache/broker, and reverse proxy all run as containers, orchestrated with `docker-compose`. A fresh clone + `docker compose up` must produce a working local environment with no manual host-level setup beyond copying `.env`.
- **This is an internal business system, not a public website.** There is no public-facing marketing site, no SEO, no anonymous signup. Every screen sits behind login. Design decisions (i18n scope, caching, admin exposure) should optimize for a small number of authenticated internal/dealer users, not internet-scale public traffic.
- **The system must support three languages: English, Dari, and Pashto.** Dari and Pashto are RTL languages written in Perso-Arabic script. This applies to the UI only (labels, menus, messages) — not to translating customer/business data itself. See §11.
- **Every third-party API integration must be toggle-able and optional at runtime via `.env`.** The app must run fully with all third-party integrations turned off, with zero real credentials configured, and nothing may crash or block startup because a key is missing. See §12.
- **Financial and audit-relevant tables are append-only.** Never design a table where a payment or cost correction is an `UPDATE`/`DELETE` — always a new row. See §6.
- **No provider logic hard-coded into business apps.** Sales, Vehicles, and Finance apps must never import `whatsapp`, `telegram`, `meta_graph`, etc. directly. They only ever call the Notification Engine / Conversation Hub interface. See §7.
- **Every model with money needs an explicit currency field.** Never store a converted total as the source of truth. See §9.
- **Multi-tenancy is shared-schema with `company_id` on every tenant-scoped table**, enforced through a custom manager/queryset, not left to per-view discipline.
- **Django Admin is for Super Admin only.** Every other role uses the app's own UI, never `/admin/`. See §8.

---

## 2. Technology Stack

| Layer | Choice |
|---|---|
| Backend framework | Django (latest LTS) monolith, Django Templates + HTMX for UI (no separate SPA) |
| API layer | Django REST Framework, for future mobile/AI consumers — read-only for MVP |
| Database | PostgreSQL 16 |
| Cache / broker | Redis |
| Async tasks | Celery (worker) + Celery Beat (scheduled tasks) |
| Styling | Tailwind CSS |
| Admin | Django Admin (locked down by role, used for internal ops only) |
| Auth | Django's built-in auth + custom role/permission model (§8) |
| Containerization | Docker + docker-compose |
| Reverse proxy (prod) | Nginx |
| App server (prod) | Gunicorn |
| File/media storage | Local volume for dev; S3-compatible object storage for prod (env-driven, don't hard-code) |
| Testing | pytest + pytest-django |
| Migrations | Django migrations (never hand-edit the schema) |
| i18n | Django's built-in `django.utils.translation` + `.po`/`.mo` catalogs for English, Dari (`fa-af` or a project-defined `prs` locale), Pashto (`ps`) |

Do not introduce additional frameworks (no FastAPI, no Node backend, no separate React app) unless explicitly instructed later. Keep the stack boring and monolithic — that is a deliberate architectural decision, not an oversight.

---

## 3. Docker Requirements

### 3.1 Services

The `docker-compose.yml` must define at minimum:

- `web` — Django app served by Gunicorn (Django dev server only in a `docker-compose.override.yml` used for local dev)
- `worker` — Celery worker, same image as `web`, different entrypoint
- `beat` — Celery Beat scheduler, same image as `web`
- `db` — PostgreSQL 16, named volume for data persistence
- `redis` — Redis, used as both Celery broker and Django cache backend
- `nginx` — reverse proxy in front of `web` (production compose file only)

### 3.2 Files to produce

- `Dockerfile` — multi-stage build (builder stage installs deps, final stage is slim runtime image). Non-root user. No dev dependencies in the final image.
- `docker-compose.yml` — base file usable in production
- `docker-compose.override.yml` — local dev overrides (bind-mounted source, Django runserver, DEBUG=True, no Nginx)
- `.dockerignore` — exclude `.git`, `__pycache__`, `*.pyc`, `.env`, `media/`, `node_modules` if any
- `.env.example` — every environment variable the app reads, with safe placeholder values, documented inline with a one-line comment each

### 3.3 Rules

- No secrets in the image or in `docker-compose.yml` — everything sensitive comes from `.env` (git-ignored) via `env_file:`.
- `web`, `worker`, and `beat` must share the **same image**, differing only by container `command`. Do not build three separate images for one codebase.
- Health checks: `db` and `redis` must have `healthcheck:` blocks; `web`/`worker`/`beat` must `depends_on` them with `condition: service_healthy`.
- Migrations run as an explicit step (entrypoint script or a one-off `docker compose run web python manage.py migrate`), never silently inside `CMD` without logging.
- Static files: `collectstatic` runs at image build time or container start, output to a shared volume Nginx reads from directly — Django's app server should never serve static files in production.

---

## 4. Directory Structure

```
automex_carflow/
│
├── config/                     # Django project settings, split by environment
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── celery.py
│   └── urls.py
│
├── apps/
│   ├── accounts/                # users, roles, permissions
│   ├── organizations/            # company/tenant model
│   ├── branches/
│   ├── vehicles/
│   ├── inventory/
│   ├── customers/
│   ├── suppliers/
│   ├── sales/
│   ├── purchases/
│   ├── payments/                 # append-only ledger lives here
│   ├── expenses/
│   ├── accounting/
│   ├── documents/
│   ├── communications/           # Conversation Hub — see §7
│   ├── notifications/
│   ├── workflows/                 # rules/alerts engine — Phase 2
│   ├── reports/
│   ├── audit/
│   └── ai/                        # Phase 3 only
│
├── templates/
├── static/
├── media/
├── docker/
│   ├── web/Dockerfile
│   ├── nginx/nginx.conf
│   └── entrypoint.sh
├── docker-compose.yml
├── docker-compose.override.yml
├── .dockerignore
├── .env.example
├── requirements/
│   ├── base.txt
│   ├── dev.txt
│   └── prod.txt
├── pytest.ini
└── AGENT.md
```

Do not deviate from this structure without a stated reason in the PR/commit message.

---

## 5. Multi-Tenancy

- Every tenant-scoped model inherits from a shared `TenantModel` abstract base with `company = ForeignKey(Organization)`.
- A custom manager (`TenantManager`) filters querysets by the company in the current request context (set via middleware from the logged-in user's company, never from client-supplied input).
- `branches` is a child scope under `organizations` — a `Branch` FK sits alongside `company` on models that are branch-specific (Sales, Inventory).
- Write a `TenantMiddleware` early — every other app depends on it existing. This is a Phase 1, Step 1 task.

---

## 6. Financial Ledger Design

- `payments`, `expenses`, and vehicle cost adjustments are modeled as **immutable ledger entries**: `LedgerEntry(type, amount, currency, related_object, created_by, created_at, reversal_of=FK[self, null])`.
- Corrections are new rows referencing `reversal_of`, never edits or deletes.
- Current-state values (e.g., "total vehicle cost," "outstanding balance") are **computed views/aggregates over the ledger**, not stored columns that can drift out of sync.
- `VehicleCostLine` follows the same pattern: one row per cost event (purchase, transport, customs, storage, repair), not a fixed set of decimal columns on `Vehicle`.
- Use `django-simple-history` for general model-level audit trail (who changed what field, when) — this is separate from and in addition to the financial ledger.

---

## 7. Conversation Hub (Communications Layer)

This is the most architecturally important app. Build it as reusable infrastructure from the first line of code, even though Phase 1 only wires up one channel.

### 7.1 Core models (`apps/communications`)

```
Channel                  (company FK, type: whatsapp|messenger|instagram|telegram|email|sms, credentials JSONB, active)
Conversation              (customer FK, channel FK, external_thread_id, assigned_to FK[User, null], status, last_message_at)
Message                   (conversation FK, direction: in|out, body, media JSONB, external_message_id,
                            status: queued|sent|delivered|read|failed, raw_payload JSONB, created_at)
CustomerChannelIdentity    (customer FK, channel FK, external_id, created_at)
```

### 7.2 Adapter interface

Every provider implements the same interface — define it as an abstract base class in `apps/communications/adapters/base.py`:

```python
class BaseChannelAdapter:
    def send(self, conversation, content: OutboundContent) -> SendResult: ...
    def parse_webhook(self, request) -> list[NormalizedInboundMessage]: ...
    def verify_signature(self, request) -> bool: ...
```

- `MetaAdapter` (shared code for WhatsApp/Messenger/Instagram — same Graph API, same webhook verification, same app credentials; branch only on `messaging_product`/object type inside the payload)
- `TelegramAdapter` (Phase 2)
- `EmailAdapter` (Phase 2)
- `SMSAdapter` (Phase 2)

Business apps (Sales, Payments, etc.) never import an adapter directly. They call a single entry point:

```python
notification_engine.notify(event="payment_recorded", company=..., customer=..., context={...})
```

The Notification Engine looks up the customer's preferred/available channels and dispatches through the Conversation Hub. This indirection is what lets you add Messenger/Instagram in Phase 1.5 without touching Sales or Payments code.

### 7.3 Webhooks

- One inbound endpoint per provider family: `/webhooks/meta/`, `/webhooks/telegram/`, etc.
- The view does **only**: verify signature → enqueue raw payload to Celery → return `200` immediately. All parsing, customer resolution, and side effects happen in the Celery task, not the view. Meta retries for up to 7 days on non-200 responses, so speed and idempotency here matter.
- Store `raw_payload` on every `Message` row before any parsing — schema changes from providers should never cause data loss, only a reprocessing job.
- Deduplicate on `external_message_id` — webhook redelivery must not create duplicate `Message` rows.

### 7.4 Customer identity resolution

On inbound message: look up `CustomerChannelIdentity` by `(channel, external_id)`. If none exists, create a new `Customer` + identity row, and flag the `Conversation` as unassigned for a rep to claim. Never silently merge two different external IDs into one customer without an explicit match (e.g., matching phone numbers across channels) — mismatches here corrupt CRM data.

---

## 8. Roles & Permissions

Implement as a `Role` model with a many-to-many to granular `Permission` objects (beyond Django's default app-level permissions — you need object-level, tenant-scoped checks). Ship these roles in Phase 1: Super Admin, Organization Admin, Branch Manager, Sales, Inventory, Accountant. Support custom roles as a Phase 2 refinement, but design the `Role`/`Permission` tables to support it from the start so it isn't a schema migration later.

### 8.1 Django Admin scope

`/admin/` is reserved exclusively for the **Super Admin** role, used for low-level operational/debugging access (fixing a bad record, inspecting raw data) — it is not the interface any dealer, branch manager, sales rep, accountant, or org admin ever sees.

- Set `is_staff=True` only on Super Admin users; every other role must have `is_staff=False` so Django's own login-required-for-admin check locks them out by default — do not rely solely on a custom permission check.
- Register only the models a Super Admin genuinely needs for support/debugging (not every model needs an `admin.py` entry). Do not build out `list_display`/`list_filter` polish for admin — it's an operational tool, not a product surface. Time spent polishing Django Admin is time not spent on the app's real UI.
- All day-to-day work (sales, inventory, payments, conversations) happens through the app's own Django Templates + HTMX UI, built with role-based views/permissions from §8, never through admin.

---

## 9. Currency Handling

- Every model with a monetary value stores `amount` + `currency` (ISO code) together — never a bare `DecimalField` assumed to be one implicit currency.
- Conversion happens only at the display/reporting layer, using a rate fetched/stored at the time of conversion — never bake a converted number back into a source-of-truth table.
- Given AFN/USD mixed transactions (import costs in USD, local sales in AFN), this is not optional — build it in Phase 1, not retrofitted later.

---

## 10. Build Order (follow exactly, do not reorder)

### Phase 1 — MVP
1. Docker skeleton: `Dockerfile`, `docker-compose.yml` + override, `.env.example` (with every `*_ENABLED` flag from §12 already listed and defaulted to `False`), healthchecks. Confirm `docker compose up` boots an empty Django project — with zero third-party credentials in `.env` — before writing any app code.
2. `config/settings` split (base/dev/prod), Celery wiring, Redis cache backend, i18n setup from §11 (`LANGUAGES`, `LocaleMiddleware`, base `locale/` catalogs for en/prs/ps), and the `*_ENABLED` settings-validation check from §12.1.
3. `organizations`, `branches`, `accounts` (custom user model with `preferred_language`, Role/Permission — Super Admin flagged `is_staff=True`, all other roles `is_staff=False`), `TenantMiddleware` + `TenantModel`/`TenantManager`. Base template with `dir="rtl"`/`dir="ltr"` switching and the language switcher.
4. `vehicles`, `inventory`.
5. `suppliers`, `purchases` (including `VehicleCostLine`, landed cost).
6. `customers`, `sales` (lead → quotation → reservation → sale → invoice).
7. `payments`, `expenses`, `accounting` — build the append-only `LedgerEntry` model first; everything else in this step reads/writes through it.
8. `audit` — wire `django-simple-history` onto tenant-scoped models.
9. `communications` + `notifications` — build the full adapter interface, Conversation Hub schema, and the Null/Console adapter fallback from §12.2 for every channel type. Implement the **real** Meta/WhatsApp adapter behind `META_ENABLED`. Payment-recorded and sale-completed events trigger a WhatsApp notification end-to-end when enabled, and a logged no-op when disabled.
10. `documents` — vehicle photos/docs, customer document uploads; storage backend switches between local filesystem and S3 per `S3_ENABLED` (§12.2).
11. Run `makemessages` for every template/string added so far, get an initial Dari/Pashto translation pass in place (even a placeholder pass), and spot-check RTL layout on the core screens (vehicle list, sale flow, conversation inbox).
12. Write pytest coverage for the ledger (§6), tenant isolation (§5), and the "every integration off" boot/test path (§12) before calling Phase 1 done — these are the highest-cost-to-get-wrong pieces.
13. Production `docker-compose.yml` (Nginx, Gunicorn, collectstatic + compiled `.mo` files, no bind mounts) — confirm parity with dev compose, and confirm it still boots cleanly with all integrations off.

### Phase 1.5
13. `MessengerAdapter` and `InstagramAdapter` (extend `MetaAdapter`, reuse Meta auth/webhook plumbing).
14. Lead Ads webhook → auto-create `Lead`; click-to-WhatsApp `referral` payload capture on first inbound message.

### Phase 2
15. `TelegramAdapter`, `EmailAdapter`, `SMSAdapter`.
16. `workflows` — rules/alerts engine (inventory aging, payment overdue, document expiry) built on Celery Beat, dispatching through the same Notification Engine entry point from §7.2.
17. `reports`.

### Phase 3
18. `ai` app — only after Phase 1/1.5 have produced real transaction and conversation history. Do not stub AI features with fake data to "get ahead" — build the pipes, wait for data, then build the models.

---

## 11. Internationalization (English / Dari / Pashto)

The system is internal-only, so i18n scope is narrower than a public product: translate the **UI chrome** (navigation, labels, buttons, form field names, validation/system messages, notification templates), not user-entered business data (a vehicle's make/model, a customer's name, free-text notes stay exactly as entered).

### 11.1 Setup

- `USE_I18N = True`, `LANGUAGES = [("en", "English"), ("prs", "Dari"), ("ps", "Pashto")]` in `config/settings/base.py`. Use `"prs"` (ISO 639-3 for Dari) as the locale code unless the team prefers `"fa-af"` — pick one and use it consistently across settings, `<html lang="">`, and translation file directory names.
- `django.middleware.locale.LocaleMiddleware` placed correctly in `MIDDLEWARE` (after `SessionMiddleware`, before `CommonMiddleware`).
- Every user-facing string in templates and Python code is wrapped: `{% trans %}` / `{% blocktrans %}` in templates, `gettext`/`gettext_lazy` in Python (use the lazy form for anything evaluated at import time — model field labels, form labels, choices).
- `locale/en/LC_MESSAGES/django.po`, `locale/prs/LC_MESSAGES/django.po`, `locale/ps/LC_MESSAGES/django.po` — generated via `django-admin makemessages -l prs -l ps` and compiled via `compilemessages`. Compiling `.mo` files happens at Docker image build time, not left to run at container start.
- Do **not** use per-language duplicate template files (`template_en.html`, `template_ps.html`) — one template, `{% trans %}` tags, separate `.po` catalogs. Duplicated templates are a maintenance trap the moment a layout changes.

### 11.2 Language selection

- Each `User` has a `preferred_language` field, set at account creation and changeable from account settings — this drives their session language, not IP/browser detection (internal users, not public visitors).
- A simple language switcher in the top nav sets the session language and reloads; no need for locale-prefixed URLs (`/en/...`, `/ps/...`) since this isn't a public, crawlable site — session-based language switching is sufficient and simpler.

### 11.3 RTL support

Dari and Pashto are RTL. This is a real layout concern, not just text direction:

- Set `dir="rtl"` / `dir="ltr"` on `<html>` dynamically based on the active language (Django's `get_language_bidi()` / `{% if LANGUAGE_BIDI %}`).
- Build Tailwind layouts using **logical CSS properties** (`ms-4`/`me-4` instead of `ml-4`/`mr-4`, `text-start`/`text-end` instead of `text-left`/`text-right`) from the start — retrofitting RTL onto a left/right-hardcoded UI later is expensive. This applies to every template built in every phase, not just a later "RTL pass."
- Test every new screen in all three languages before marking a feature done, not just English — an untested Dari/Pashto layout is effectively a broken feature for a meaningful share of your users.
- Numbers, dates, and currency formatting should follow Django's locale-aware formatting (`{% load l10n %}`), not be manually formatted per template.

### 11.4 What is explicitly out of scope

- Translating stored business data (vehicle descriptions, customer names, notes) — these stay in whatever language the user typed them.
- Machine-translating WhatsApp/Telegram/SMS message *content* sent by customers — the Conversation Hub stores and displays what was actually sent, unmodified. (A future AI-assisted "translate this message" button is a Phase 3 AI-layer feature, not part of core i18n.)
- Public/anonymous-facing pages — there are none in this system.

## 12. Third-Party Integration Toggle Pattern

Every external API integration — S3, Meta (WhatsApp/Messenger/Instagram), Telegram, SMS gateway, email/SMTP — must be **fully optional at runtime**. The application must start, run migrations, run its full test suite, and be usable end-to-end with every third-party integration switched off and zero real credentials present anywhere in the environment. This is required for local dev, CI, and any environment where a client hasn't yet supplied their API keys.

### 12.1 The pattern

For every integration, `.env.example` defines one boolean flag plus its credential variables, e.g.:

```
# --- Meta (WhatsApp / Messenger / Instagram) ---
META_ENABLED=False
META_APP_ID=
META_APP_SECRET=
META_ACCESS_TOKEN=
META_WEBHOOK_VERIFY_TOKEN=

# --- Telegram ---
TELEGRAM_ENABLED=False
TELEGRAM_BOT_TOKEN=

# --- SMS Gateway ---
SMS_ENABLED=False
SMS_GATEWAY_URL=
SMS_GATEWAY_API_KEY=

# --- Email ---
EMAIL_ENABLED=False
EMAIL_HOST=
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=

# --- S3-compatible object storage ---
S3_ENABLED=False
S3_ENDPOINT_URL=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET_NAME=
```

- When `*_ENABLED=False`: the credential variables may be blank. **Settings validation must not raise, and the app must not refuse to boot**, regardless of which flags are off.
- When `*_ENABLED=True`: settings validation (a startup check, e.g. in `AppConfig.ready()` or a dedicated `manage.py check` custom check) **must** raise a clear, actionable error if any required credential for that integration is missing — fail fast and specifically ("META_ENABLED=True but META_ACCESS_TOKEN is not set"), not with a generic exception three layers deep at send time.

### 12.2 How adapters implement "off"

Every adapter from §7.2 and the storage backend follows the same shape: a factory function reads the relevant `*_ENABLED` flag and returns either the **real adapter** or a **Null/Console adapter**, and calling code never knows which one it got.

```python
def get_channel_adapter(channel_type: str) -> BaseChannelAdapter:
    if channel_type == "meta" and not settings.META_ENABLED:
        return NullChannelAdapter(channel_type)   # logs + no-ops, never calls Graph API
    if channel_type == "meta":
        return MetaAdapter(...)
    ...
```

- `NullChannelAdapter.send(...)` logs the outbound message (to the console/log, and still writes the `Message` row with `status="skipped_disabled"`) instead of calling a real API, and returns success — so the rest of the app (Sales, Payments, Notification Engine) behaves identically whether the integration is live or off. No business-logic code should ever branch on "is this integration enabled" — only the factory does.
- Same pattern for storage: when `S3_ENABLED=False`, `DEFAULT_FILE_STORAGE` falls back to Django's local filesystem storage, writing to the `media/` volume — no code elsewhere references S3 directly.
- Same pattern for email: when `EMAIL_ENABLED=False`, use Django's `console.EmailBackend` (prints to log) instead of SMTP.
- Webhook endpoints for a disabled integration (e.g. `/webhooks/meta/` when `META_ENABLED=False`) should still exist and return a clear `503`/explanatory response rather than 404ing or crashing, so flipping the flag on later requires no code changes — only `.env` changes and a container restart.

### 12.3 Why this matters for this project

This lets development, staging, demos, and client onboarding proceed without waiting on WhatsApp Business verification, Telegram bot setup, or S3 credentials — all of which have external lead times outside your control (see the Meta verification timeline discussed earlier in this project). A client should be able to turn on WhatsApp the day their Meta Business verification clears, by editing `.env` and restarting containers — nothing else.

## 13. Testing & CI expectations

- Every app ships with `tests/` using pytest-django and factory_boy for fixtures.
- Tenant isolation and ledger immutability tests are mandatory gates before merging Phase 1.
- `docker compose run web pytest` must be the standard way tests are run — no "works on my machine" host-level test execution.

## 14. What NOT to do

- Do not hard-code any provider (WhatsApp, Telegram, SMS, Email) logic inside `sales`, `payments`, `vehicles`, or any business app — always go through `notification_engine`.
- Do not store computed financial totals as the source of truth — compute from `LedgerEntry`.
- Do not build the AI layer before Phase 1/1.5 are live with real data.
- Do not deviate from the shared-image (`web`/`worker`/`beat`) Docker pattern.
- Do not process webhook payloads synchronously inside the webhook view.
- Do not require any real third-party credential to be present for the app to build, migrate, boot, or pass tests — every integration must degrade to a Null/Console adapter when its `*_ENABLED` flag is `False`.
- Do not hardcode English-only strings in new templates or forms — wrap everything translatable from the moment it's written, not as a retrofit pass later.
- Do not use left/right-hardcoded Tailwind spacing/alignment classes in new templates — use logical properties so RTL (Dari/Pashto) isn't a rebuild.
- Do not give any role other than Super Admin `is_staff=True` or access to `/admin/`.
- Do not build public-facing, anonymous, or SEO-oriented pages — this is an internal system behind login only.