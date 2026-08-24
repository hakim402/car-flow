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
3. [Data model reference](#data-model-reference)
4. [Technology stack](#technology-stack)
5. [Repository layout](#repository-layout)
6. [Prerequisites](#prerequisites)
7. [Quick start](#quick-start)
8. [Users, companies, and roles](#users-companies-and-roles)
9. [Configuration reference (`.env`)](#configuration-reference-env)
10. [Everyday Docker commands](#everyday-docker-commands)
11. [Logging & observability](#logging--observability)
12. [Development workflow](#development-workflow)
13. [Testing](#testing)
14. [Internationalization (i18n)](#internationalization-i18n)
15. [Ports](#ports)
16. [Integrations overview](#integrations-overview)
17. [Backups](#backups)
18. [Deployment](#deployment)
19. [Security practices](#security-practices)
20. [Troubleshooting](#troubleshooting)

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

`web`, `worker`, and `beat` share ONE image — `automex-carflow:dev` in
development, `automex-carflow:prod` in production (separate tags so the two
modes never overwrite each other); the container `command` selects the role
via `docker/entrypoint.sh`. The entrypoint waits
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

## Data model reference

> Generated from `apps/*/models.py`, `apps/*/services.py` and `apps/*/views.py`.
> The system has **23 Django models** across 14 apps. `expenses` and
> `accounting` deliberately define **no models** — an expense is a
> `LedgerEntry` row and accounting is computed from ledger rows. `core`
> contributes only abstract bases (`TenantModel`, `ImmutableModel`).
> `django-simple-history` adds 9 auto-generated `Historical*` tables on top
> (see [Audit history](#audit-history)).

### Model inventory (all 23 models)

| # | App | Model | Base classes | Purpose |
|---|-----|-------|--------------|---------|
| 1 | `accounts` | `Permission` | `models.Model` | One granular permission token (`sales.view`, `payments.add`, …) |
| 2 | `accounts` | `Role` | `models.Model` | Named bundle of permissions; 6 system roles seeded by migration |
| 3 | `accounts` | `User` | `AbstractUser` | Staff login — identifier is the **email**, not the username |
| 4 | `organizations` | `Organization` | `models.Model` | **The tenant** — a company / dealership group |
| 5 | `branches` | `Branch` | `models.Model` | Child scope under a company (unique name per company) |
| 6 | `vehicles` | `Vehicle` | `TenantModel` | Vehicle registry (VIN unique per company) |
| 7 | `inventory` | `VehicleStock` | `TenantModel` | One stock row per vehicle currently held at a branch |
| 8 | `suppliers` | `Supplier` | `TenantModel` | Business / individual sellers and agents |
| 9 | `purchases` | `PurchaseOrder` | `TenantModel` | PO header (domestic or import, shipment tracking) |
| 10 | `purchases` | `PurchaseOrderLine` | `models.Model` | One PO line — the link between a purchase and a vehicle |
| 11 | `purchases` | `VehicleCostLine` | `TenantModel` + `ImmutableModel` | One immutable cost event per vehicle (landed-cost ledger) |
| 12 | `customers` | `Customer` | `TenantModel` | Buyer directory |
| 13 | `sales` | `Lead` | `TenantModel` | Pipeline stage 1 |
| 14 | `sales` | `Quotation` | `TenantModel` | Pipeline stage 2 |
| 15 | `sales` | `Reservation` | `TenantModel` | Pipeline stage 3 (flips the vehicle to reserved) |
| 16 | `sales` | `Sale` | `TenantModel` | Pipeline stage 4 |
| 17 | `sales` | `Invoice` | `TenantModel` + `ImmutableModel` | Issued invoice — append-only, one per sale |
| 18 | `payments` | `LedgerEntry` | `TenantModel` + `ImmutableModel` | **The append-only financial ledger** |
| 19 | `documents` | `Document` | `TenantModel` | Photo/document attached to vehicle, customer or supplier |
| 20 | `communications` | `Channel` | `TenantModel` | A configured messaging channel (WhatsApp, Messenger, …) |
| 21 | `communications` | `Conversation` | `TenantModel` | One thread with a customer on a channel |
| 22 | `communications` | `Message` | `TenantModel` | One message row (inbound / outbound) |
| 23 | `communications` | `CustomerChannelIdentity` | `TenantModel` | Maps one external sender id to exactly one customer |

### Entity relationship map

```
Organization (tenant — the root of everything)
├── Branch
│     └── branch-scoped rows: User, Vehicle, VehicleStock, Customer, Lead,
│                             PurchaseOrder (all carry an optional branch FK)
├── User ── roles (M2M) ── Role ── permissions (M2M) ── Permission
│
├── Supplier ── PurchaseOrder ── lines ── PurchaseOrderLine
│                                            └── vehicle (FK) ──► Vehicle
│
├── Customer ◄── Lead
│              Quotation ── customer (FK) ──► Customer
│              Reservation ─ customer + vehicle (FK)
│              Sale ─ customer + vehicle (+ optional reservation)
│              Invoice ── sale (FK, immutable, one per sale)
│
├── LedgerEntry (immutable)
│      ├── related_object (GenericFK) ──► Sale / Supplier / any model
│      └── reversal_of (self FK) ──► LedgerEntry
│
├── Document (FK vehicle | customer | supplier — exactly one target)
│
├── Vehicle ── VehicleStock (OneToOne, branch)
│      └── VehicleCostLine (FK vehicle, immutable, landed-cost ledger)
│
└── Channel ── Conversation (customer + channel + external thread id)
       │             └── Message (FK conversation; unique external id)
       └── CustomerChannelIdentity (customer + channel + external id)
```

### How the models connect — the eight links

1. **The tenant root.** Every `TenantModel` carries `company` (FK →
   `Organization`, PROTECT). `Branch` also points to `Organization`;
   branch-scoped records (`Vehicle`, `VehicleStock`, `Customer`, `Lead`,
   `PurchaseOrder`) additionally carry an optional `branch` FK. The
   `TenantManager` auto-filters every query to the request's company;
   `all_objects` is the explicit Super-Admin escape hatch.

2. **Users, roles, permissions.** `User.roles` (M2M → `Role`) →
   `Role.permissions` (M2M → `Permission`, codenames like `sales.view`).
   `User.company` is null only for Super Admin; `User.save()` keeps
   `is_staff` in sync with the Super Admin role / superuser flag, which
   locks Django Admin to Super Admin only.

3. **Purchasing chain.** `Supplier` → `PurchaseOrder` (FK supplier,
   PROTECT) → `PurchaseOrderLine` (FK order, CASCADE) → `Vehicle` (FK
   vehicle, PROTECT, optional). The supplier of a vehicle is *derived* —
   `Vehicle.source_supplier` returns the supplier of the first purchase
   line that references the vehicle.

4. **Receiving side effects.** `receive_order()` writes into
   `VehicleCostLine` (one immutable row per vehicle line), updates
   `Vehicle`, and creates `VehicleStock`. A vehicle's total cost
   (`vehicle_landed_cost`) is an aggregate over `VehicleCostLine` rows —
   never a stored column.

5. **Sales pipeline.** `Customer` ← `Lead` → `Quotation` → `Reservation` →
   `Sale` → `Invoice`. Quotation / Reservation / Sale each FK → `Customer`
   (PROTECT) and → `Vehicle` (PROTECT; Quotation's is optional). Creating a
   reservation flips the vehicle to `RESERVED`; completing a sale flips it
   to `SOLD`, closes the active reservation, and issues at most one
   immutable `Invoice` (`INV-{pk:06d}`).

6. **The money spine.** Every money movement is one immutable `LedgerEntry`
   row: `customer_payment` (money **in**, GFK → `Sale`), `supplier_payment`
   (money **out**, GFK → `Supplier`), `expense` (money **out**, no GFK),
   `other` (money **in**). Corrections are NEW rows whose `reversal_of` FK
   points at the original. All balances / outstanding amounts are computed
   aggregates (`apps/accounting/services.py`) — per currency, never
   converted.

7. **Documents.** `Document` has three nullable FKs (`vehicle`, `customer`,
   `supplier`) — the form enforces exactly one target. `doc_type` plus the
   per-target type lists (`VEHICLE_DOC_TYPES`, `CUSTOMER_DOC_TYPES`,
   `SUPPLIER_DOC_TYPES`) restrict what each upload box can create.

8. **Conversation Hub.** `Channel` (type + credentials JSON) →
   `Conversation` (customer + channel + external thread id) → `Message`
   (direction, status, raw payload). `CustomerChannelIdentity` maps an
   external sender id to exactly one `Customer` — unknown senders create a
   new customer (never silently merged). Business apps only ever call
   `notification_engine.notify(...)`.

### Model dictionary — every column of every model

#### `accounts.Permission` — granular permission token

Tenant-scoped permission token beyond Django's app-level permissions.
Business views check these for object-level access.

| Column | Type | Details |
|---|---|---|
| `codename` | `CharField(100)` | **Unique.** E.g. `sales.view`, `payments.add`. Seeded by migration `0003_seed_permissions`. |
| `description` | `CharField(255)` | Optional human-readable description. |

#### `accounts.Role` — named bundle of permissions

| Column | Type | Details |
|---|---|---|
| `key` | `SlugField(50)` | **Unique.** E.g. `org_admin`, `branch_manager`. |
| `name` | `CharField(100)` | Display name. |
| `system` | `BooleanField` | Default `False`, non-editable; `True` for the 6 seeded roles. |
| `permissions` | M2M → `Permission` | Optional. |

Seeded roles (migration `0002_seed_builtin_roles`): `super_admin`,
`org_admin`, `branch_manager`, `sales`, `inventory`, `accountant`.
Permission grants (migration `0003_seed_permissions`) follow
`{app}.{action}` codenames (`view`/`add`/`change`) over the 10 business
apps; `org_admin` gets all of them, the other roles get subsets.

#### `accounts.User` — internal staff login

Login identifier is the **email** (`USERNAME_FIELD = "email"`); `username`
survives only as an optional legacy/display label. Inherits all standard
`AbstractUser` columns (`password`, `last_login`, `is_superuser`,
`first_name`, `last_name`, `is_active`, `date_joined`, `groups`,
`user_permissions`) plus:

| Column | Type | Details |
|---|---|---|
| `username` | `CharField(150)` | Null/blank — optional label only. |
| `email` | `EmailField` | **Unique.** The login id. |
| `company` | FK → `Organization` | `PROTECT`. Null/blank **only for Super Admin**. |
| `branch` | FK → `Branch` | `PROTECT`. Null/blank. |
| `roles` | M2M → `Role` | Optional. |
| `preferred_language` | `CharField(8)` | Default `en`; choices `en` / `prs` / `ps`. Drives the session language after login. |

Model logic: `has_role(key)`, `is_super_admin` property,
`permission_codenames()`, `has_permission(codename)` (superuser bypasses),
and `save()` keeps `is_staff = has_super_admin or is_superuser` in sync,
which is what locks Django Admin to Super Admin.

#### `organizations.Organization` — the tenant

Not tenant-scoped itself — it **is** the tenant.

| Column | Type | Details |
|---|---|---|
| `name` | `CharField(200)` | Company name. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

#### `branches.Branch` — child scope under a company

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | `PROTECT`. |
| `name` | `CharField(200)` | |
| `created_at` | `DateTimeField` | `auto_now_add`. |

Constraint: **unique `(company, name)`**.

#### `vehicles.Vehicle` — vehicle registry (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel` (`PROTECT`). |
| `vin` | `CharField(17)` | Vehicle Identification Number. |
| `make` | `CharField(100)` | |
| `model` | `CharField(100)` | |
| `year` | `PositiveSmallIntegerField` | |
| `color` | `CharField(50)` | Optional. |
| `mileage` | `PositiveIntegerField` | Default `0`. |
| `status` | `CharField(20)` | `in_transit` / `in_stock` / `reserved` / `sold` / `delivered`; default `in_transit`. |
| `branch` | FK → `Branch` | `PROTECT`. Null/blank. |
| `notes` | `TextField` | Optional. |
| `created_at` / `updated_at` | `DateTimeField` | Auto. |

Constraint: **unique `(company, vin)`**. Deliberately **no cost columns** —
cost is computed from `VehicleCostLine` rows. Properties:
`primary_photo` (oldest vehicle photo), `source_supplier` (derived from
purchase lines).

#### `inventory.VehicleStock` — branch stock row (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `vehicle` | `OneToOneField` → `Vehicle` | `PROTECT`. One stock row per vehicle. |
| `branch` | FK → `Branch` | `PROTECT`. Where the car sits. |
| `status` | `CharField(20)` | `available` / `reserved` / `in_preparation`; default `available`. |
| `lot_code` | `CharField(50)` | Optional parking/lot code. |
| `received_at` | `DateTimeField` | `auto_now_add`. |

Created by purchase receiving; branch users only see their branch's rows.

#### `suppliers.Supplier` — supplier directory (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `name` | `CharField(200)` | |
| `kind` | `CharField(20)` | `business` / `individual`; default `business`. |
| `supplier_type` | `CharField(20)` | `local_dealer` / `overseas_dealer` / `auction` / `broker` / `shipping_agent` / `other`; default `local_dealer`. |
| `national_id` | `CharField(50)` | Optional (tazkera / national ID). |
| `country` | `CharField(5)` | `COUNTRIES` choices; optional. |
| `contact_person` | `CharField(200)` | Optional. |
| `phone` | `CharField(50)` | Optional. |
| `email` | `EmailField` | Optional. |
| `address` | `TextField` | Optional. |
| `notes` | `TextField` | Optional. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

Properties: `is_individual`; `logo` (most recent `supplier_logo` /
`supplier_photo` document).

#### `purchases.PurchaseOrder` — PO header (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `reference` | `CharField(50)` | Optional free-text reference. |
| `supplier` | FK → `Supplier` | `PROTECT`. |
| `branch` | FK → `Branch` | `PROTECT`. Null/blank. |
| `status` | `CharField(20)` | `draft` / `ordered` / `shipped` / `customs` / `received` / `cancelled`; default `draft`. |
| `purchase_type` | `CharField(20)` | `domestic` / `import`; default `domestic`. |
| `order_date` | `DateField` | Required. |
| `origin_country` | `CharField(5)` | Optional; **required by the form for imports**. |
| `incoterms` | `CharField(10)` | `EXW` / `FOB` / `CFR` / `CIF` / `DAP` / `DDP`; optional. |
| `shipping_method` | `CharField(20)` | `container` / `ro_ro` / `land` / `air` / `other`; optional. |
| `bill_of_lading_no` | `CharField(100)` | Optional. |
| `container_no` | `CharField(100)` | Optional. |
| `shipped_date` | `DateField` | Null/blank. |
| `eta` | `DateField` | Null/blank. |
| `notes` | `TextField` | Optional. |
| `created_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` / `updated_at` | `DateTimeField` | Auto. |

Logic: `total_by_currency()` (computed from lines, never stored);
`is_import`; `next_status` — imports walk `draft → ordered → shipped →
customs` (`NEXT_STATUS` map), domestic orders go `draft → ordered` and
then straight to receiving. `RECEIVED` is reachable **only** through
`receive_order()`.

#### `purchases.PurchaseOrderLine` — one PO line

**Not tenant-scoped** (a child of the tenant-scoped order).

| Column | Type | Details |
|---|---|---|
| `order` | FK → `PurchaseOrder` | `CASCADE`. |
| `vehicle` | FK → `Vehicle` | `PROTECT`. Null/blank — **the car↔purchase link**. |
| `description` | `CharField(255)` | |
| `amount` | `DecimalField(14, 2)` | |
| `currency` | `CharField(3)` | `CURRENCIES`; default `AFN`. |

#### `purchases.VehicleCostLine` — immutable vehicle cost event (`TenantModel` + `ImmutableModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `vehicle` | FK → `Vehicle` | `PROTECT`. |
| `cost_type` | `CharField(20)` | `purchase` / `transport` / `customs` / `storage` / `repair` / `other`. |
| `amount` | `DecimalField(14, 2)` | |
| `currency` | `CharField(3)` | Default `AFN`. |
| `description` | `CharField(255)` | Optional. |
| `created_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

**Immutable:** `save()` on an existing row raises `ImmutableRecordError`;
`delete()` always raises. `vehicle_landed_cost(vehicle)` sums these rows
per currency.

#### `customers.Customer` — buyer directory (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `full_name` | `CharField(200)` | |
| `phone` | `CharField(50)` | Optional. |
| `email` | `EmailField` | Optional. |
| `national_id` | `CharField(50)` | Optional. |
| `branch` | FK → `Branch` | `PROTECT`. Null/blank. |
| `notes` | `TextField` | Optional. |
| `created_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` / `updated_at` | `DateTimeField` | Auto. |

Property: `primary_photo` (oldest customer photo).

#### `sales.Lead` — pipeline stage 1 (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `name` | `CharField(200)` | Lead's name. |
| `phone` | `CharField(50)` | Optional. |
| `customer` | FK → `Customer` | `PROTECT`. Null/blank. |
| `vehicle_of_interest` | FK → `Vehicle` | `SET_NULL`. Null/blank. |
| `source` | `CharField(20)` | `walk_in` / `phone` / `whatsapp` / `referral` / `other`; default `walk_in`. |
| `status` | `CharField(20)` | `new` / `contacted` / `qualified` / `converted` / `lost`; default `new`. |
| `branch` | FK → `Branch` | `PROTECT`. Null/blank. |
| `notes` | `TextField` | Optional. |
| `created_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` / `updated_at` | `DateTimeField` | Auto. |

#### `sales.Quotation` — pipeline stage 2 (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `customer` | FK → `Customer` | `PROTECT`. |
| `vehicle` | FK → `Vehicle` | `PROTECT`. Null/blank. |
| `lead` | FK → `Lead` | `SET_NULL`. Null/blank. |
| `amount` | `DecimalField(14, 2)` | |
| `currency` | `CharField(3)` | Default `AFN`. |
| `valid_until` | `DateField` | Required. |
| `status` | `CharField(20)` | `draft` / `sent` / `accepted` / `declined` / `expired`; default `draft`. |
| `notes` | `TextField` | Optional. |
| `created_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` / `updated_at` | `DateTimeField` | Auto. |

#### `sales.Reservation` — pipeline stage 3 (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `customer` | FK → `Customer` | `PROTECT`. |
| `vehicle` | FK → `Vehicle` | `PROTECT`. |
| `quotation` | FK → `Quotation` | `PROTECT`. Null/blank. |
| `deposit_amount` | `DecimalField(14, 2)` | |
| `currency` | `CharField(3)` | Default `AFN`. |
| `status` | `CharField(20)` | `active` / `completed` / `cancelled`; default `active`. |
| `notes` | `TextField` | Optional. |
| `created_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` / `updated_at` | `DateTimeField` | Auto. |

Logic: creating a reservation (atomic) flips an `IN_STOCK` vehicle to
`RESERVED` so it cannot be double-sold.

#### `sales.Sale` — pipeline stage 4 (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `customer` | FK → `Customer` | `PROTECT`. |
| `vehicle` | FK → `Vehicle` | `PROTECT`. |
| `reservation` | FK → `Reservation` | `PROTECT`. Null/blank. |
| `agreed_amount` | `DecimalField(14, 2)` | |
| `currency` | `CharField(3)` | Default `AFN`. |
| `sale_date` | `DateField` | Required. |
| `status` | `CharField(20)` | `draft` / `completed` / `cancelled`; default `draft`. |
| `notes` | `TextField` | Optional. |
| `created_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` / `updated_at` | `DateTimeField` | Auto. |

Logic: `complete_sale()` (atomic, DRAFT only) flips the vehicle to `SOLD`,
closes the active reservation, and notifies the customer;
`issue_invoice()` is idempotent — one immutable invoice per sale.

#### `sales.Invoice` — immutable issued invoice (`TenantModel` + `ImmutableModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `sale` | FK → `Sale` | `PROTECT`. |
| `number` | `CharField(50)` | Generated as `INV-{sale.pk:06d}`. |
| `issued_on` | `DateField` | |
| `amount` | `DecimalField(14, 2)` | Copied from the sale. |
| `currency` | `CharField(3)` | |
| `created_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

Constraint: **unique `(company, number)`**. Immutable like all financial
rows — corrections go through the ledger, never by editing an invoice.

#### `payments.LedgerEntry` — the append-only ledger (`TenantModel` + `ImmutableModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `type` | `CharField(30)` | `customer_payment` / `supplier_payment` / `expense` / `other`. |
| `amount` | `DecimalField(14, 2)` | Always positive; direction comes from `type`. |
| `currency` | `CharField(3)` | Default `AFN`. |
| `description` | `CharField(255)` | Optional. |
| `content_type` | FK → `ContentType` | `PROTECT`. Null/blank (GenericFK part 1). |
| `object_id` | `BigIntegerField` | Null/blank (GenericFK part 2). |
| `related_object` | `GenericForeignKey` | The business row the money relates to (`Sale`, `Supplier`, …). |
| `reversal_of` | FK → `LedgerEntry` (self) | `PROTECT`. Null/blank — points at the corrected row. |
| `created_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

Money direction map (`ENTRY_DIRECTION`): `customer_payment` → **in**,
`supplier_payment` → **out**, `expense` → **out**, `other` → **in**.
Properties: `direction`, `signed_amount` (±). Corrections are new rows
created by `reverse_entry()` with the same type/amount/currency/GFK and
`reversal_of` pointing at the original — updates and deletes raise
`ImmutableRecordError` at the model level.

#### `documents.Document` — file attachments (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `vehicle` | FK → `Vehicle` | `PROTECT`. Null/blank. |
| `customer` | FK → `Customer` | `PROTECT`. Null/blank. |
| `supplier` | FK → `Supplier` | `PROTECT`. Null/blank. |
| `doc_type` | `CharField(30)` | 18 choices — see below; default `other`. |
| `title` | `CharField(255)` | Optional. |
| `file` | `FileField` | `upload_to="documents/%Y/%m/"`. |
| `uploaded_by` | FK → `User` | `PROTECT`. Null/blank. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

`doc_type` choices: `vehicle_photo`, `license`, `sale_document`,
`insurance`, `customs`, `inspection`, `vehicle_document`, `customer_photo`,
`tazkera`, `passport`, `electricity_bill`, `other_bill`, `customer_document`,
`supplier_logo`, `supplier_photo`, `supplier_license`, `supplier_document`,
`other`. Exactly one of `vehicle`/`customer`/`supplier` is required (form
level); each upload box restricts the type picker to its list
(`VEHICLE_DOC_TYPES`, `CUSTOMER_DOC_TYPES`, `SUPPLIER_DOC_TYPES`).
Property: `is_photo` splits galleries from paperwork.

#### `communications.Channel` — messaging channel config (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `type` | `CharField(20)` | `whatsapp` / `messenger` / `instagram` / `telegram` / `email` / `sms`. |
| `credentials` | `JSONField` | Default `{}`; e.g. `{"phone_number_id": "…"}`. |
| `active` | `BooleanField` | Default `True`. |

#### `communications.Conversation` — one thread (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `customer` | FK → `Customer` | `PROTECT`. |
| `channel` | FK → `Channel` | `PROTECT`. |
| `external_thread_id` | `CharField(255)` | Optional provider thread id. |
| `assigned_to` | FK → `User` | `SET_NULL`. Null/blank. |
| `status` | `CharField(20)` | `open` / `closed`; default `open`. |
| `last_message_at` | `DateTimeField` | Null/blank; bumped on every message. |

#### `communications.Message` — one message (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `conversation` | FK → `Conversation` | `CASCADE`. |
| `direction` | `CharField(5)` | `in` (inbound) / `out` (outbound). |
| `body` | `TextField` | |
| `media` | `JSONField` | Default `[]`. |
| `external_message_id` | `CharField(255)` | Optional provider id. |
| `status` | `CharField(20)` | `queued` / `sent` / `delivered` / `read` / `failed` / `skipped_disabled`; default `queued`. |
| `raw_payload` | `JSONField` | Null/blank — the raw provider payload persisted **before** parsing. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

Constraint: **unique `(company, external_message_id)`** where
`external_message_id ≠ ""` — webhook redelivery can never create
duplicates.

#### `communications.CustomerChannelIdentity` — sender id map (`TenantModel`)

| Column | Type | Details |
|---|---|---|
| `company` | FK → `Organization` | From `TenantModel`. |
| `customer` | FK → `Customer` | `PROTECT`. |
| `channel` | FK → `Channel` | `PROTECT`. |
| `external_id` | `CharField(255)` | The provider's sender id. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

Constraint: **unique `(company, channel, external_id)`** — one external id
maps to exactly one customer; distinct ids are never merged silently.

### Abstract bases (not tables)

- **`TenantModel`** (`apps/core/tenancy.py`) — adds `company` FK →
  `Organization` (`PROTECT`, `related_name="+"`) and replaces `objects`
  with `TenantManager` (auto-filtered by the request tenant via a
  `ContextVar`); `all_objects` is the explicit unfiltered escape hatch.
- **`ImmutableModel`** (`apps/core/models.py`) — `save()` raises
  `ImmutableRecordError` when editing an existing row; `delete()` always
  raises. Used by `VehicleCostLine`, `LedgerEntry`, `Invoice`.

### Audit history

`apps/audit/apps.py` registers `django-simple-history` on 9 models:
`Vehicle`, `VehicleStock`, `Supplier`, `PurchaseOrder`, `Customer`, `Lead`,
`Quotation`, `Reservation`, `Sale` — producing 9 auto-generated
`Historical*` tables. `LedgerEntry`, `VehicleCostLine` and `Invoice` are
deliberately **not** registered (they are already immutable append-only
rows). `HistoryRequestMiddleware` records the acting user on each history
row.

### Full business logic by domain

#### 1. Multi-tenancy (`apps/core`)

- `TenantMiddleware` reads the **authenticated user's company** (never
  client input) and sets a request-scoped `ContextVar`; it resets the
  context when the request finishes.
- `TenantManager.get_queryset()` filters by that company when the context
  is set; without context (Super Admin, shell, Celery) it returns
  unfiltered rows — Super Admin's dashboard therefore shows platform-wide
  totals through the same manager.
- `for_current_company()` raises `NoTenantContext` when used outside a
  tenant context; background jobs wrap themselves in `company_scope()`.
- Every create view stamps `obj.company = request.user.company` and raises
  `PermissionDenied` for company-less (Super Admin) users; forms scope FK
  querysets through the tenant managers and validate branch ownership
  (e.g. `VehicleForm.clean` rejects a foreign branch).

#### 2. Auth, roles, permissions (`apps/accounts`)

- Login is by **email**; `CarFlowLoginView` activates the user's
  `preferred_language` immediately after authentication (sets the
  `django_language` session key + cookie — Django 5's LocaleMiddleware
  reads the cookie).
- `require_permission(codename)` decorates every business view:
  unauthenticated → redirect to login; missing permission → 403.
- `User.save()` keeps `is_staff` in lockstep with the Super Admin role /
  superuser flag — Django Admin (`/admin/`) is Super Admin only. Super
  Admin (`company=None`) manages tenants in Admin; business records are
  created by company users.
- `set_language` POST updates the language cookie, the session, and
  `User.preferred_language`, then reloads the same page.
- `admin_dashboard_callback` adds platform KPI cards (companies, branches,
  users, roles) to the Unfold admin home.

#### 3. Vehicles & inventory (`apps/vehicles`, `apps/inventory`)

- `Vehicle` is unique per `(company, vin)` and carries **no cost columns**.
- Lifecycle: `in_transit` → `in_stock` (purchase receiving) → `reserved`
  (reservation created) → `sold` (`complete_sale`) → `delivered`.
- Branch users see only their branch's fleet (list filtered by
  `request.user.branch_id`); search matches VIN/make/model; status filter
  validates against `VehicleStatus.values`.
- `VehicleStock` is OneToOne per vehicle, created at receiving; its status
  (`available` / `reserved` / `in_preparation`) is maintained manually
  from the inventory list; inventory lists are branch-scoped for branch
  users.

#### 4. Purchasing & receiving (`apps/purchases`)

- Status machine: `draft → ordered → shipped → customs → received`
  (imports) or `draft → ordered → received` (domestic), plus `cancelled`;
  `order_advance` moves one legal step at a time via `next_status`;
  `RECEIVED` is reachable **only** through `receive_order()`.
- Import orders must set `origin_country` (form validation).
- `receive_order()` runs in one transaction and is idempotent per line:
  returns `0` if the order is already `RECEIVED`; for every line with a
  vehicle it appends one `VehicleCostLine` (type `purchase`, amount /
  currency from the line, description `"PO {order}"`) unless an identical
  row already exists, sets the vehicle's branch (order branch or the
  vehicle's own) and status `IN_STOCK`, and `get_or_create`s the
  `VehicleStock`; finally flips the order to `RECEIVED` and returns the
  number of vehicles received.
- `vehicle_add_cost` appends any other cost event (transport, customs,
  storage, repair, other) — immutable rows, corrections are new rows.
- `vehicle_landed_cost(vehicle)` aggregates cost lines per currency;
  conversion happens only at display time.

#### 5. Sales pipeline (`apps/sales`)

- Create views stamp `company` + `created_by`; `Lead` and `Quotation`
  statuses update via POST endpoints that validate the status value.
- `reservation_create` (atomic) flips an `IN_STOCK` vehicle to `RESERVED`
  so it cannot be double-sold.
- `sale_detail` computes `can_complete` (status is `draft`) and
  `can_invoice` (status is `completed` and no invoice exists yet).
- `complete_sale()` (atomic): DRAFT-only → sale `COMPLETED`, vehicle
  `SOLD`, active reservation `COMPLETED`, then notifies the customer with
  the `sale_completed` event (notification failure is logged and never
  breaks the sale).
- `issue_invoice()` is idempotent: if an invoice exists it returns it;
  otherwise creates the immutable `Invoice` with number `INV-{pk:06d}`,
  today's date, and the sale's amount/currency. The view refuses to issue
  before the sale is completed.

#### 6. Money & accounting (`apps/payments`, `apps/expenses`, `apps/accounting`)

- **Everything writes through the ledger.** `record_payment()` creates one
  `customer_payment` row (GFK → `Sale`) and fires the `payment_recorded`
  notification (never breaks the ledger write); `record_supplier_payment()`
  creates a `supplier_payment` row (GFK → `Supplier`); `record_expense()`
  creates an `expense` row with no GFK.
- `reverse_entry()` corrects a row by appending its **mirror image**: same
  type, amount, currency, GFK, plus `reversal_of` → the original row.
- `_net_totals()` (accounting) is the heart of every figure: a reversal
  row is counted **against its original row's direction** and negated, so
  an expense reversal reduces money-out while a payment reversal reduces
  money-in.
- Derived figures — all per currency, never converted:
  `ledger_balance()` (in − out), `money_in()` (gross received, net of
  payment reversals), `money_out()` (gross paid, net of reversals),
  `sale_payments(sale)`, `sale_outstanding(sale)` (agreed amount − paid),
  `supplier_payments(supplier)` (net paid to a supplier).
- The accounting summary view renders balance, money in/out, and the
  outstanding amount of every completed sale — all computed from ledger
  rows.

#### 7. Expenses (`apps/expenses`)

- No model. The list view filters `LedgerEntry` by `type=expense`; the
  create view writes through `record_expense(company, …)`. Company-less
  users are denied.

#### 8. Documents (`apps/documents`)

- One upload view, four shapes: generic (`DocumentForm` — requires at
  least one of vehicle/customer/supplier), or locked to a vehicle /
  customer / supplier (`VehicleDocumentForm`, `CustomerDocumentForm`,
  `SupplierDocumentForm`) with the target as a hidden field and the
  `doc_type` picker restricted to the target's allowed type list.
- After upload the user lands back on the target's detail page. `is_photo`
  splits galleries vs paperwork; card thumbnails/avatars/logos use
  prefetched lists (`photo_list`, `logo_list`, `purchase_line_list`) to
  avoid per-card queries.
- Storage is decided only in settings: local `media/` volume by default,
  S3 when `S3_ENABLED` is on (`STORAGES` block); app code only uses
  `FileField`.

#### 9. Conversation Hub & notifications (`apps/communications`)

- **Outbound:** business code calls exactly one function —
  `notification_engine.notify(event, company, customer, context)`. Known
  events and templates: `payment_recorded` ("Payment of {amount}
  {currency} was recorded…"), `sale_completed` ("Your purchase of
  {vehicle} is complete…"). The engine translates the template, resolves
  the customer's active channel identities, `get_or_create`s a
  `Conversation` per identity, and sends via `send_reply` — returning the
  number of attempts. Unknown events or missing context log and return 0.
- `send_reply()` calls the channel adapter and persists the attempt: Null
  adapter (integration off) → `skipped_disabled`; success → `sent`;
  failure → `failed`. Bumps `conversation.last_message_at`.
- **Inbound:** `process_inbound_payload()` dedupes on `external_message_id`
  first, resolves the customer (`resolve_customer`: known identity →
  existing customer; unknown → **new customer** named "<Channel display>
  <last 6 digits>" + a new identity row — never a silent merge), then
  stores the message (direction `in`, status `delivered`, raw payload) and
  bumps `last_message_at`.
- **Meta webhook** (`/webhooks/meta/`): GET performs the `hub.mode=
  subscribe` URL-verification handshake (echoes `hub.challenge` only when
  `META_ENABLED` and the verify token match; otherwise 403). POST:
  refuses with **503** while disabled; verifies the HMAC-SHA256
  `X-Hub-Signature-256` signature against `META_APP_SECRET` (403 on
  mismatch); rejects unparseable bodies with 400; then enqueues
  `process_meta_webhook.delay(payload)` and returns **200 immediately** —
  Meta retries up to 7 days on non-200, so the endpoint stays fast and
  idempotent.
- The Celery task `process_meta_webhook` replays one payload against every
  active Meta-family channel (`Channel.all_objects`) — dedupe constraints
  make redelivery harmless.
- `get_channel_adapter()` is the **only** place that reads `*_ENABLED`
  flags: Meta family + `META_ENABLED` → `MetaAdapter`, everything else →
  `NullChannelAdapter`. `MetaAdapter` sends through the Graph API `v19.0`
  `/{endpoint_id}/messages` endpoint (Bearer `META_ACCESS_TOKEN`, 15 s
  timeout), picks the endpoint id from the channel's credentials with env
  fallbacks, and normalizes inbound payloads walking
  `entry → changes → value → messages`.

#### 10. Audit (`apps/audit`)

- `django-simple-history` records every change on the 9 business models;
  `HistoryRequestMiddleware` stamps the acting user; immutable financial
  rows are excluded by design.

#### 11. Integration toggles (`config/checks.py`)

- System check `carflow.E001` fails startup fast when an `*_ENABLED` flag
  is `True` but any of its required credentials is blank (named variable
  in the error); with every flag off, boot must succeed with empty
  credentials — the test suite enforces this contract.

#### 12. i18n & RTL (`config/settings/base.py`, `apps/accounts/views.py`)

- Languages `en` (English), `prs` (Dari), `ps` (Pashto); `prs` and `ps`
  are registered in `LANG_INFO` and `LANGUAGES_BIDI` so templates render
  `dir="rtl"` automatically.
- Language switching persists in three places: the `django_language`
  cookie (what LocaleMiddleware actually reads), the session (legacy
  compatibility), and `User.preferred_language` (used at next login).

#### 13. Dashboard (`apps/accounts/views.py`)

- Company users see KPIs: vehicles in stock, open leads (new / contacted /
  qualified), active (draft) sales, customer count, and the 5 latest
  sales. Super Admin (no company) additionally sees platform totals
  (companies + users) and, in `/admin/`, the Unfold KPI cards.

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
#    http://localhost:8000           → redirects to the login page
```

`docker compose up` automatically applies `docker-compose.override.yml`
(development mode: source bind-mounted, Django dev server with auto-reload,
DEBUG on, Nginx dormant) and serves on **http://localhost:8000**. Migrations
run automatically in the `web` container on every start.

> **Two modes, two ports:** bare `docker compose ...` = development on
> `DEV_PORT` (default **8000**); `docker compose -f docker-compose.yml ...` =
> production (Nginx + Gunicorn) on `NGINX_PORT` (default **8765**).
> Containers share the same names, so run only one mode at a time:
> `docker compose down` before switching.

Sanity check from a terminal:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/accounts/login/
# → 200  (production stack: use http://localhost:8765 instead)
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

Log in at `http://localhost:8000/admin/` (dev) — or `http://localhost:8765/admin/`
on the production stack — and create, in order:

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
# Dev stack:
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/accounts/login/
# Production stack:
curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/accounts/login/
```

All services carry `restart: unless-stopped`, so they come back
automatically after a Docker Desktop / machine restart.

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
npm run css
# or without the package scripts:
# npx tailwindcss@3.4.17 -i css/input.css -o static/css/tailwind.css --minify
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

Dev and production use **different** host ports so the two stacks never
collide:

| Mode | Variable | Default | Mapping |
|---|---|---|---|
| Development | `DEV_PORT` | `8000` | `${DEV_PORT:-8000}` → Django dev server `8000` |
| Production | `NGINX_PORT` | `8765` | `${NGINX_PORT:-8765}` → Nginx `80` |

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
| `port is already allocated` on `up` | The other mode's stack is still holding the port — `docker compose down` first, or change `DEV_PORT`/`NGINX_PORT` in `.env`. |
| App containers stuck in `Created` after switching modes | Dev and prod share container names. Run `docker compose down`, then start the mode you want (bare commands = dev, `-f docker-compose.yml` = prod). |
| `403 CSRF verification failed` on form POST | Plain-HTTP stack with Secure cookies: set `COOKIES_SECURE=False` in `.env`, then `docker compose up -d --force-recreate web` (add `-f docker-compose.yml` for the prod stack). HTTPS deployments keep it `True`. |
| `403` + log line `Origin checking failed - … does not match any trusted origins` | The browser's `Origin` header isn't trusted. Origins are auto-derived from `DJANGO_ALLOWED_HOSTS` + port; if your URL differs, set `DJANGO_CSRF_TRUSTED_ORIGINS=https://your.host` in `.env` and recreate `web`. |
| `403 Forbidden (Permission denied)` on app pages like `/vehicles/add/` | Those pages are company-scoped — the logged-in user must belong to a company with a suitable role. Super Admin (`company=None`) manages tenants via `/admin/`; day-to-day records are added by a company user (e.g. Organization Admin). |
| Locked out of `/admin/` | Access requires `is_staff`, which is kept in sync with the Super Admin role / superuser flag on save — re-save the user or tick **Staff status** only for Super Admins (§8.1). |
| `IntegrityError … pg_type_typname_nsp_index` on first boot | Corrupted first-migration state: `docker compose down -v` then `docker compose up`. (Prevented structurally: only the web service migrates.) |
| `pytest: not found` in the container | Dev image missing/not built yet: `docker compose build web` (dev and prod use separate tags `:dev` / `:prod`, so they can coexist). |
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
