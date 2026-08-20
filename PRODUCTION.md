# AUTOMEX CarFlow — Production Guide

This guide covers deploying CarFlow on a server: the production compose
stack, PostgreSQL setup (containerized or external), user & role
management, Nginx/HTTPS, backups, and operations.

For local development see [`README.md`](README.md).

---

## 1. Production architecture

```
Internet
   │  :${NGINX_PORT:-8765}
┌──▼───────────────────────────────────────────────────────┐
│ nginx            serves /static/ and /media/ directly,   │
│                  proxies everything else to web:8000     │
└──┬───────────────────────────────────────────────────────┘
   │
┌──▼─────────┐    ┌─────────┐    ┌─────────┐
│ web        │    │ worker  │    │ beat    │   ← ONE image, 3 roles
│ (Gunicorn) │    │ (Celery)│    │ (Beat)  │
└──┬─────┬───┘    └──┬───┬──┘    └──┬───┬──┘
   │     └───────────┼───┴──────────┼───┘
┌──▼─────┐      ┌────▼───┐
│ db     │      │ redis  │   cache + Celery broker
│ PG 16  │      └────────┘
└────────┘
```

Key behaviors:

- `docker-compose.yml` alone **is** the production stack
  (`docker-compose.override.yml` is dev-only and is *not* applied when you
  pass `-f docker-compose.yml` explicitly).
- The `web` role is the **only** one that runs migrations; worker/beat just
  wait for the database (concurrent `migrate` corrupts PostgreSQL).
- Static files are collected at image build time and served by Nginx from a
  shared volume; media uploads live on the `media_data` volume.
- Settings module: `config.settings.prod` (DEBUG off, secure cookies,
  console email unless `EMAIL_ENABLED`, real logging).

---

## 2. Server prerequisites

- Linux server with **Docker Engine + Compose plugin** (any recent x86_64
  distro). Nothing else — no Python, no PostgreSQL, no Node required.
- Inbound access to the port you choose (default **8765**; 80/443 if you
  terminate TLS at the edge).
- Enough disk for the database, uploaded media, and Docker images.

```bash
docker --version        # >= 24 recommended
docker compose version  # >= 2.20 recommended
```

---

## 3. First deployment

```bash
# 1. Get the code
git clone https://github.com/hakim402/car-flow.git
cd car-flow

# 2. Environment file
cp .env.example .env

# 3. Generate a strong secret key and edit .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
#    → paste the result into DJANGO_SECRET_KEY
```

Mandatory `.env` values for production:

```dotenv
DJANGO_SECRET_KEY=<long random value>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=carflow.example.com,www.carflow.example.com

DB_NAME=carflow
DB_USER=carflow
DB_PASSWORD=<strong random password>
DB_HOST=db
DB_PORT=5432

NGINX_PORT=8765        # host port users will hit

# Leave every *_ENABLED flag False until you really configure a provider.
```

```bash
# 4. Build and start (detached)
docker compose -f docker-compose.yml up -d --build

# 5. Verify
docker compose -f docker-compose.yml ps          # db/redis must be healthy
docker compose -f docker-compose.yml logs web    # migrations + Gunicorn boot
curl -I http://localhost:8765/accounts/login/    # → HTTP 200
```

The app is now reachable at `http://<server-ip>:8765/`.

### Changing the port

Set `NGINX_PORT` in `.env` (e.g. `NGINX_PORT=9000`) and restart:

```bash
docker compose -f docker-compose.yml up -d
```

Only the host mapping changes; Nginx still listens on 80 *inside* the
container. To serve on standard 80/443, put a TLS-terminating proxy in front
(see section 8) or map `NGINX_PORT=80` and add your own certificate setup.

---

## 4. PostgreSQL

### 4a. Default: the managed `db` container

The compose file creates a `postgres:16-alpine` container. Database, user,
and password come straight from `.env` (`DB_NAME`, `DB_USER`,
`DB_PASSWORD`) — the container initializes a fresh cluster with that
user/database on first start, and data persists in the `postgres_data`
volume.

Connect to it:

```bash
docker compose -f docker-compose.yml exec db psql -U carflow -d carflow
```

### 4b. Creating a database with a specific user (manual / external PG)

If you prefer an external PostgreSQL server (managed service or a
dedicated container), create the role and database first — CarFlow's
migrations need ownership-level privileges on the schema:

```sql
-- as the postgres superuser
CREATE USER carflow_app WITH PASSWORD 'REPLACE_WITH_STRONG_PASSWORD';
CREATE DATABASE carflow OWNER carflow_app;

-- recommended hardening
ALTER ROLE carflow_app SET client_encoding TO 'utf8';
ALTER ROLE carflow_app SET default_transaction_isolation TO 'read committed';
ALTER ROLE carflow_app SET timezone TO 'UTC';

GRANT ALL PRIVILEGES ON DATABASE carflow TO carflow_app;
```

Then point the app at it in `.env`:

```dotenv
DB_NAME=carflow
DB_USER=carflow_app
DB_PASSWORD=REPLACE_WITH_STRONG_PASSWORD
DB_HOST=<pg host or service name>
DB_PORT=5432
```

If you run the external PG as its own container in the same compose project,
you can drop the built-in `db` service from a copy of the compose file, or
simply leave it unused (it only starts when referenced).

> Do **not** run the app against the `postgres` superuser account in
> production. Create a dedicated owner role as above.

### 4c. Backups & restore

```bash
# Backup (timestamped dump on the host)
docker compose -f docker-compose.yml exec -T db \
  pg_dump -U carflow -d carflow > backup_$(date +%F).sql

# Restore into a fresh stack
docker compose -f docker-compose.yml exec -T db \
  psql -U carflow -d carflow < backup_2026-08-20.sql
```

Media files live in the `media_data` volume — snapshot/copy them alongside
the SQL dump if you use local storage (`S3_ENABLED=False`).

---

## 5. Users, companies, branches, roles

Everything is behind login. Bootstrap order:

### 5a. Create the Super Admin

```bash
docker compose -f docker-compose.yml exec web python manage.py createsuperuser
```

The Super Admin is the **only** role allowed into Django Admin (`/admin/`)
— `is_staff` is kept in lockstep with the role, so no other user can even
see the admin login.

### 5b. Create a company and its staff

Log in at `/admin/` and create:

1. **Organization** — the tenant (company/dealership group).
2. **Branch** — optional, one or more per organization.
3. **User** — set `company` (required for non-superusers), optionally
   `branch`, and attach `roles`. Set `preferred_language`
   (`en` / `prs` / `ps`) — this drives the UI language.

Or via shell:

```bash
docker compose -f docker-compose.yml exec web python manage.py shell
```

```python
from apps.organizations.models import Organization
from apps.branches.models import Branch
from apps.accounts.models import Role, User

org = Organization.objects.create(name="AUTOMEX Kabul")
branch = Branch.objects.create(company=org, name="Main")

u = User.objects.create_user(
    username="sales1", password="change-me-strong",
    company=org, branch=branch, preferred_language="prs",
)
u.roles.add(Role.objects.get(key="sales"))
u.save()
```

### 5c. Built-in roles

Seeded by migrations:

| Role key | Purpose |
|---|---|
| `super_admin` | Platform owner; sole access to Django Admin; no company. |
| `org_admin` | Runs a company: manages branches, users, all data. |
| `branch_manager` | Manages one branch's inventory and staff activity. |
| `sales` | Leads, quotations, reservations, sales, payments. |
| `inventory` | Vehicles, stock, receiving. |
| `accountant` | Payments, expenses, accounting summaries. |

### 5d. Adding roles and permissions

Roles are plain database rows — custom roles need no code changes.

**Via admin (as Super Admin):** create `Permission` tokens
(e.g. `exports.view`), bundle them into a `Role`, assign the role to users.

**Via shell:**

```python
from apps.accounts.models import Permission, Role

perm, _ = Permission.objects.get_or_create(
    codename="reports.export",
    description="Export financial reports",
)
role, _ = Role.objects.get_or_create(
    key="auditor", defaults={"name": "Auditor"}
)
role.permissions.add(perm)

# grant to a user
from apps.accounts.models import User
User.objects.get(username="finance1").roles.add(role)
```

Business views check permissions with `user.has_permission("<codename>")`.

### 5e. Day-2 account operations

```bash
# reset a password
docker compose -f docker-compose.yml exec web python manage.py changepassword sales1

# list users of a company
docker compose -f docker-compose.yml exec web python manage.py shell -c \
  "from apps.accounts.models import User; print(list(User.objects.filter(company__name='AUTOMEX Kabul').values_list('username', flat=True)))"
```

---

## 6. Nginx in this stack

`docker/nginx/nginx.conf` is mounted read-only into the `nginx` service:

- `client_max_body_size 25m` — document upload limit.
- `/static/` and `/media/` served straight from shared volumes with caching
  headers (Django never sees these requests).
- Everything else proxied to `web:8000` with `X-Forwarded-Proto` set —
  `config.settings.prod` trusts that header via `SECURE_PROXY_SSL_HEADER`,
  which is what makes secure cookies work behind TLS.

To tweak limits or headers, edit `docker/nginx/nginx.conf` and reload:

```bash
docker compose -f docker-compose.yml restart nginx
```

---

## 7. HTTPS / TLS termination

Two common patterns:

### 7a. Reverse proxy in front of the stack (recommended)

Run Caddy/Traefik/your existing Nginx on the host edge, obtain the
certificate there (e.g. Let's Encrypt), and forward to the stack's
`NGINX_PORT`:

```
Caddyfile example:
carflow.example.com {
    reverse_proxy localhost:8765
}
```

Ensure `DJANGO_ALLOWED_HOSTS` contains the domain. Secure-cookie settings
already work because the proxy sends `X-Forwarded-Proto: https`.

### 7b. Certbot on the containerized Nginx

Add certbot, mount `./certs` and obtain the certificate for your domain,
then extend `docker/nginx/nginx.conf`:

```nginx
server {
    listen 80;
    server_name carflow.example.com;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    server_name carflow.example.com;
    ssl_certificate     /etc/letsencrypt/live/carflow.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/carflow.example.com/privkey.pem;

    client_max_body_size 25m;

    location /static/ { alias /app/staticfiles/; expires 30d; }
    location /media/  { alias /app/media/;      expires 7d;  }
    location / {
        proxy_pass http://carflow_web;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

(Keep the `upstream carflow_web { server web:8000; }` block, mount the cert
directory into the nginx service, and map port 443.)

---

## 8. Enabling integrations (when ready)

Every provider is a toggle + credentials in `.env`; **no code changes**.
While a flag is off the system uses Null/console adapters and persists
outbound attempts as `skipped_disabled`.

| Provider | Toggle | Credentials |
|---|---|---|
| WhatsApp / Messenger / Instagram | `META_ENABLED=True` | `META_APP_ID`, `META_APP_SECRET`, `META_ACCESS_TOKEN`, `META_WEBHOOK_VERIFY_TOKEN`, per-product page/phone IDs |
| Telegram | `TELEGRAM_ENABLED=True` | `TELEGRAM_BOT_TOKEN` (adapter arrives in Phase 2) |
| SMS | `SMS_ENABLED=True` | `SMS_GATEWAY_URL`, `SMS_GATEWAY_API_KEY` |
| Email | `EMAIL_ENABLED=True` | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` |
| S3 storage | `S3_ENABLED=True` | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_NAME` |

After editing `.env`:

```bash
docker compose -f docker-compose.yml up -d
```

Meta webhook endpoint: `https://<your-domain>:<port>/webhooks/meta/`
(GET handshake with `hub.verify_token` = `META_WEBHOOK_VERIFY_TOKEN`).
The endpoint refuses payloads with 503 while `META_ENABLED=False`.

---

## 9. Updates, rollbacks, operations

```bash
# Deploy a new version
git pull
docker compose -f docker-compose.yml up -d --build   # rebuild + migrate on web start

# Logs
docker compose -f docker-compose.yml logs -f web worker beat

# Restart one role
docker compose -f docker-compose.yml restart worker

# Full stop (data kept)
docker compose -f docker-compose.yml down

# Rollback a bad deploy
git checkout <previous-commit>
docker compose -f docker-compose.yml up -d --build
```

Migrations are applied automatically by the `web` container's entrypoint on
every start — there is no separate migration step to remember. Roll forward
only: migrations are additive; if you must roll back code that shipped a
migration, restore from backup rather than reversing schema by hand.

### Health checks

```bash
docker compose -f docker-compose.yml ps
# db, redis report (healthy); web/worker/beat report Up
curl -I http://localhost:8765/accounts/login/    # expect 200
```

---

## 10. Security checklist

- [ ] `DJANGO_DEBUG=False`
- [ ] Strong random `DJANGO_SECRET_KEY` (never committed)
- [ ] Strong `DB_PASSWORD`; app runs as a dedicated PG role, not `postgres`
- [ ] `DJANGO_ALLOWED_HOSTS` lists only your real domain(s)
- [ ] HTTPS terminated in front; `X-Forwarded-Proto` forwarded
- [ ] Only the HTTP(S) port exposed publicly — PostgreSQL and Redis ports
      stay inside the Docker network
- [ ] `.env` file permissions restricted (`chmod 600 .env`)
- [ ] Every `*_ENABLED` flag off until the provider is actually configured
- [ ] Regular `pg_dump` backups (+ media volume) tested with a restore
- [ ] Super Admin account used only for admin tasks; daily work happens
      under company-scoped roles
