AUTOMEX CarFlow
> **Authoritative target architecture and implementation contract for coding agents.**
>
> This README describes the design CarFlow **must converge to**. If the existing
> code conflicts with this document, agents must update the implementation and
> migrations rather than preserving obsolete behavior. Preserve existing data
> safely during migrations.
AUTOMEX CarFlow is an internal, multi-company automotive ERP for dealerships
that buy vehicles from local individuals, domestic dealers, foreign dealers,
auctions, and other suppliers; manage receiving and inventory; run a CRM and
sales pipeline; collect customer payments; pay suppliers; record expenses;
calculate vehicle profitability; and operate an omnichannel Conversation Hub.
Area	Standard
Backend	Python 3.12 · Django 5.2 LTS
Database	PostgreSQL 16
Cache / queue	Redis 7
Background work	Celery + Celery Beat
Frontend	Django Templates + Tailwind CSS
Web server	Gunicorn behind Nginx
Storage	Local media in development; S3-compatible storage optional
Audit	`django-simple-history` + immutable financial/event records
Languages	English · Dari (`prs`) · Pashto (`ps`)
Direction	Full LTR/RTL support
Deployment	Docker; one application image with `web`, `worker`, `beat` roles
All external providers are optional. CarFlow must boot and operate with every
integration disabled and all provider credentials empty.
---
1. Product scope
CarFlow covers these connected business domains:
Organizations, branches, users, roles, and permissions.
Sellers/suppliers: individuals, domestic businesses, foreign dealers,
auctions, brokers, and logistics partners.
Vehicle acquisition and purchase orders.
Immutable per-vehicle landed-cost events.
Inventory locations, current stock state, and movement history.
Customers, leads, quotations, reservations, sales, and invoices.
Customer payments, supplier payments, cashboxes, bank accounts, and receipts.
Operating expenses and expense categories.
Operational accounting: cash position, receivables, payables, gross profit,
inventory value, and vehicle profitability.
Documents and photos.
Audit history.
Omnichannel conversations and notifications.
What CarFlow is not yet
The financial subsystem in this architecture is an operational financial
ledger, not a full statutory double-entry general ledger.
Do not claim that CarFlow has a complete balance sheet, chart of accounts,
debit/credit journal, tax engine, or statutory financial statements unless
those modules are implemented separately later.
---
2. Core architectural principles
2.1 Modular monolith
CarFlow is intentionally a Django modular monolith.
Do not split the system into microservices unless there is a demonstrated
operational need. PostgreSQL remains the source of truth.
```text
                         ┌──────────────────┐
                         │      Nginx       │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │      Django      │
                         │ Modular Monolith │
                         └────────┬─────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
     PostgreSQL                 Redis                Object Storage
    source of truth       cache / Celery broker      local / S3
                                  │
                                  ▼
                           Celery Workers
                                  │
                      ┌───────────┴───────────┐
                      ▼                       ▼
                 Notifications          Integrations
```
2.2 Hard business invariants belong below the UI
Forms are not enough.
Critical invariants must be enforced by the strongest practical combination of:
PostgreSQL constraints,
transactions,
row locks or atomic conditional updates,
service-layer validation,
model validation where appropriate,
permission checks.
Shell scripts, Celery tasks, imports, APIs, and future code can bypass forms.
2.3 Explicit money
Every monetary amount must always have a currency.
Use `Decimal`.
Never use floating point for money.
Never silently convert currencies.
Aggregates are grouped by currency unless a deliberate FX/reporting feature
is added later.
Transaction time and record-creation time are separate concepts.
2.4 Immutable financial history
Financial facts and landed-cost events are append-only.
Corrections are new records, never edits to historical monetary rows.
Application-level immutability is required, but coding agents must also use
database-level protections wherever practical so `QuerySet.update()`, raw SQL,
admin mistakes, or bulk operations cannot silently rewrite financial history.
2.5 Fail-closed tenancy
Tenant-scoped queries must never fail open.
For a `TenantModel`:
```text
request/company context exists  -> automatically filter by company
no company context              -> raise NoTenantContext
```
Unrestricted access must be explicit:
```python
Model.all_objects
```
and limited to trusted Super Admin/system operations.
Background jobs must enter an explicit:
```python
with company_scope(company):
    ...
```
Never use client-provided `company_id` to establish tenancy.
2.6 Provider isolation
Business apps never import or call provider-specific SDK/API code.
Business code calls:
```python
notification_engine.notify(...)
```
Provider routing and integration flags live only in the communications adapter
layer.
---
3. Application map
Recommended Django apps:
App	Responsibility
`core`	Tenancy, immutability, shared constraints/helpers, money utilities
`organizations`	Organizations/companies
`branches`	Branch hierarchy
`accounts`	User, roles, permissions, authentication
`suppliers`	Seller/supplier directory
`vehicles`	Permanent vehicle identity
`purchases`	Acquisition orders, PO lines, receiving, landed costs
`inventory`	Stock position, physical locations, movement history
`customers`	Customer directory
`sales`	Leads, activities, quotations, reservations, sales, invoices
`payments`	Financial accounts, ledger, payment recording/reversal
`expenses`	Expense categories and expense-facing workflow
`accounting`	Read-only financial/reporting services
`documents`	Attachments and photos
`communications`	Conversation Hub, channel adapters, webhooks
`audit`	History configuration
`accounting` should remain primarily a calculation/reporting layer. Do not
duplicate authoritative monetary values into summary models unless there is a
measured performance requirement and a clear reconciliation mechanism.
---
4. Domain model overview
```text
Organization
│
├── Branch
│    └── InventoryLocation
│
├── User ── roles ── Role ── permissions ── Permission
│
├── Supplier / Seller
│    └── PurchaseOrder
│         └── PurchaseOrderLine ──► Vehicle
│
├── Vehicle
│    ├── VehicleCostLine
│    ├── VehicleStock
│    │    └── InventoryLocation
│    └── InventoryMovement
│
├── Customer
│    ├── Lead
│    │    └── LeadActivity
│    ├── Quotation
│    ├── Reservation
│    ├── Sale
│    │    └── Invoice
│    └── CustomerChannelIdentity
│
├── FinancialAccount
│    └── LedgerEntry
│
├── ExpenseCategory
│
├── Document
│
└── Channel
     └── Conversation
          └── Message
```
---
5. Organizations, branches, users, and permissions
5.1 Organization
The organization is the tenant root.
Recommended fields:
```text
Organization
- id
- name
- created_at
```
It is not itself a `TenantModel`.
5.2 Branch
```text
Branch
- id
- company -> Organization
- name
- active
- created_at
```
Constraint:
```text
UNIQUE(company, name)
```
5.3 User
Authentication uses email as the login identifier.
```text
User
- email                         UNIQUE
- username                      optional legacy/display field
- first_name
- last_name
- company -> Organization       null only for Super Admin
- branch -> Branch              nullable
- roles -> Role M2M
- preferred_language            en / prs / ps
- is_active
- standard Django auth fields
```
A user's branch must belong to the user's company.
5.4 Roles
Seed at least:
```text
super_admin
org_admin
branch_manager
sales
inventory
accountant
```
Custom roles and permissions remain database rows.
Granular permissions follow:
```text
{domain}.{action}
```
Examples:
```text
sales.view
sales.add
sales.change
payments.add
expenses.add
inventory.transfer
```
Django Admin is restricted to Super Admin.
---
6. Sellers, suppliers, and acquisition
A vehicle acquired by AUTOMEX must always be traceable to the party from whom
it was acquired.
Use a single seller/supplier master rather than separate tables for private
people and companies.
6.1 Supplier
Keep the model name `Supplier` if preferred in code; UI text may use
Seller / Supplier.
```text
Supplier
- id
- company
- name
- kind
- supplier_type
- national_id
- country
- contact_person
- phone
- email
- address
- notes
- created_at
```
`kind`:
```text
individual
business
```
`supplier_type`:
```text
local_seller
local_dealer
overseas_dealer
auction
broker
shipping_agent
other
```
Examples:
```text
Ahmad Rahimi
kind = individual
supplier_type = local_seller
country = Afghanistan
```
```text
Tokyo Auto Export Co.
kind = business
supplier_type = overseas_dealer
country = Japan
```
6.2 PurchaseOrder
```text
PurchaseOrder
- id
- company
- reference / number
- supplier
- branch
- status
- purchase_type
- order_date
- origin_country
- incoterms
- shipping_method
- bill_of_lading_no
- container_no
- shipped_date
- eta
- notes
- created_by
- created_at
- updated_at
```
`purchase_type`:
```text
domestic
import
```
Status machine:
Domestic:
```text
DRAFT -> ORDERED -> RECEIVED
```
Import:
```text
DRAFT -> ORDERED -> SHIPPED -> CUSTOMS -> RECEIVED
```
Both may transition to `CANCELLED` only where business rules permit.
`RECEIVED` must only be reachable through the receiving service.
6.3 PurchaseOrderLine
Each line is the explicit acquisition record for a specific vehicle.
```text
PurchaseOrderLine
- id
- order -> PurchaseOrder
- vehicle -> Vehicle
- description
- amount
- currency
```
A vehicle's acquisition seller is derived through the relevant purchase line
and purchase order.
Do not permanently store `supplier_id` on `Vehicle`.
Do not define `source_supplier` as "the first PO ever" without considering
re-acquisition. If CarFlow supports a vehicle being sold and later bought back,
the current/latest acquisition must be derived from the latest valid acquisition
event.
6.4 Receiving
`receive_order()` must be:
transactional,
idempotent,
concurrency-safe.
For each vehicle line:
confirm the line belongs to the order/company,
append the purchase `VehicleCostLine` once,
create/initialize current inventory stock,
assign the receiving branch/location,
record an inventory movement of type `RECEIVE`,
set the order to `RECEIVED` after all lines succeed.
Never partly receive an order and mark the whole order received unless partial
receiving is explicitly implemented.
---
7. Vehicle identity and landed cost
7.1 Vehicle
`Vehicle` is the permanent registry identity, not the inventory status engine.
Recommended fields:
```text
Vehicle
- id
- company
- vin
- make
- model
- year
- color
- mileage
- notes
- created_at
- updated_at
```
Constraint:
```text
UNIQUE(company, vin)
```
Do not store:
```text
purchase_cost
landed_cost
profit
balance
```
as mutable columns.
7.2 VehicleCostLine
Vehicle landed cost is an append-only stream of cost events.
```text
VehicleCostLine
- id
- company
- vehicle
- cost_type
- amount
- currency
- description
- source_type / source reference as designed
- reversal_of -> VehicleCostLine nullable
- created_by
- transaction_date
- created_at
```
`cost_type`:
```text
purchase
transport
customs
storage
repair
inspection
other
```
Amounts are positive. A reversal negates the original event in calculation.
Example:
```text
Purchase          +20,000 USD
Shipping           +1,500 USD
Customs            +3,000 USD
Bad repair entry     +700 USD
Reversal              -700 USD
Correct repair        +500 USD
--------------------------------
Net landed cost     25,000 USD
```
Rules:
rows are immutable,
deletion is forbidden,
one original cost event may be reversed at most once unless a deliberate
reinstatement workflow is implemented,
a reversal must use the same company, vehicle, amount, currency, and cost
classification as the original,
landed cost is always calculated from net cost events.
---
8. Inventory architecture
`VehicleStock` is the authoritative current inventory position.
Do not maintain overlapping "availability" states independently on both
`Vehicle` and `VehicleStock`.
8.1 InventoryLocation
A branch may contain several physical locations.
```text
InventoryLocation
- id
- company
- branch
- name
- type
- code
- active
- created_at
```
Types:
```text
showroom
warehouse
yard
workshop
inspection
lot
other
```
Examples:
```text
Kabul Main Showroom
Kabul Warehouse A
Kabul Workshop
Herat Storage Yard
```
Constraint:
```text
UNIQUE(company, branch, code)    where code is populated
```
The location's branch must belong to the same company.
8.2 VehicleStock
One current stock row per vehicle.
```text
VehicleStock
- id
- company
- vehicle                  OneToOne
- branch
- location
- status
- lot_code
- condition
- received_at
- available_at
- reserved_at
- sold_at
- delivered_at
- created_at
- updated_at
```
Recommended `status`:
```text
IN_TRANSIT
RECEIVED
INSPECTION
PREPARATION
AVAILABLE
RESERVED
SOLD
DELIVERED
```
Not every vehicle must pass through every stage.
Domestic example:
```text
RECEIVED -> AVAILABLE -> RESERVED -> SOLD -> DELIVERED
```
Import example:
```text
IN_TRANSIT -> RECEIVED -> INSPECTION -> PREPARATION
-> AVAILABLE -> RESERVED -> SOLD -> DELIVERED
```
`condition` is a separate concept:
```text
NEW
EXCELLENT
GOOD
FAIR
DAMAGED
NEEDS_REPAIR
```
Do not mix condition and availability.
8.3 InventoryMovement
Current location alone is insufficient. Preserve physical history.
```text
InventoryMovement
- id
- company
- vehicle
- movement_type
- from_branch
- to_branch
- from_location
- to_location
- performed_by
- moved_at
- notes
```
Movement types:
```text
RECEIVE
TRANSFER
MOVE
RESERVE
RELEASE
SALE
DELIVERY
RETURN
ADJUSTMENT
```
Inventory services update `VehicleStock` and append the corresponding
`InventoryMovement` in one transaction.
Do not delete `VehicleStock` after sale or delivery. Historical stock data is
required for aging and reporting.
8.4 Inventory aging
Derive inventory age from dates rather than storing it.
Examples:
```text
days_in_inventory = today - received_at
days_to_sale      = sold_at - received_at
days_to_delivery  = delivered_at - received_at
```
Dashboard buckets:
```text
0-30 days
31-60 days
61-90 days
90+ days
```
---
9. Customers and CRM
9.1 Customer
```text
Customer
- id
- company
- full_name
- phone
- email
- national_id
- branch
- notes
- created_by
- created_at
- updated_at
```
Unknown inbound social senders may create a provisional customer identity, but
CarFlow must never silently merge two different external identities.
9.2 Lead
A lead represents a sales opportunity before a complete customer record is
necessarily required.
```text
Lead
- id
- company
- name
- phone
- customer                  nullable
- vehicle_of_interest       nullable
- source
- status
- branch
- assigned_to               nullable User
- lost_reason               nullable
- notes
- created_by
- created_at
- updated_at
```
Sources:
```text
walk_in
phone
whatsapp
messenger
instagram
telegram
email
referral
website
other
```
Statuses:
```text
NEW
CONTACTED
QUALIFIED
CONVERTED
LOST
```
Lost reasons:
```text
PRICE_TOO_HIGH
BOUGHT_ELSEWHERE
NO_RESPONSE
FINANCING
VEHICLE_UNAVAILABLE
CHANGED_MIND
OTHER
```
When a lead becomes a real customer:
create or select the correct `Customer`,
link `lead.customer`,
set status to `CONVERTED`.
Do not duplicate customers automatically based only on similar names.
9.3 LeadActivity
Recommended CRM activity history:
```text
LeadActivity
- id
- company
- lead
- activity_type
- notes
- performed_by
- scheduled_at
- completed_at
- created_at
```
Types:
```text
CALL
WHATSAPP
EMAIL
MEETING
SHOWROOM_VISIT
TEST_DRIVE
FOLLOW_UP
NOTE
```
---
10. Quotation
```text
Quotation
- id
- company
- number
- customer
- vehicle
- lead
- amount
- currency
- valid_until
- status
- notes
- created_by
- created_at
- updated_at
```
Status:
```text
DRAFT
SENT
ACCEPTED
DECLINED
EXPIRED
```
Number example:
```text
QT-2026-000123
```
Rules:
quotation number is unique per company,
a sent/accepted quotation is commercial history,
price revisions should normally create a new quotation or explicit revision,
not silently rewrite an accepted quote,
quotation customer/vehicle/lead must belong to the same company,
quotation currency must match any reservation created from it unless a
deliberate conversion workflow exists.
---
11. Reservation
A reservation reserves inventory. It is not itself proof that money was
received.
```text
Reservation
- id
- company
- customer
- vehicle
- quotation
- required_deposit_amount
- currency
- expires_at
- status
- notes
- created_by
- created_at
- updated_at
```
Status:
```text
ACTIVE
COMPLETED
CANCELLED
EXPIRED
```
Reservation creation
Must be concurrency-safe.
Within one transaction:
lock/select the current stock row with `select_for_update()` or perform
an atomic conditional update,
require stock status `AVAILABLE`,
ensure there is no other active reservation,
create reservation,
set `VehicleStock.status = RESERVED`,
set `reserved_at`,
append `InventoryMovement(RESERVE)`.
Database constraint:
```text
at most one ACTIVE reservation per vehicle
```
`transaction.atomic()` alone is not sufficient without locking or equivalent
atomic concurrency control.
Reservation cancellation/expiry
Within one transaction:
```text
Reservation ACTIVE -> CANCELLED / EXPIRED
VehicleStock RESERVED -> AVAILABLE
append InventoryMovement(RELEASE)
```
Celery Beat may expire overdue active reservations.
Deposit
`required_deposit_amount` means the requested deposit.
Actual money received is always a ledger/payment transaction.
Never infer "paid" from `Reservation.required_deposit_amount`.
---
12. Sale
Use separate dimensions for commercial, payment, and fulfillment state.
12.1 Sale model
```text
Sale
- id
- company
- customer
- vehicle
- reservation
- agreed_amount
- currency
- sale_date
- status
- notes
- created_by
- created_at
- updated_at
```
Commercial `status`:
```text
DRAFT
CONFIRMED
CANCELLED
```
Payment and delivery states are derived where possible:
```text
payment_status:
UNPAID
PARTIAL
PAID

delivery_status:
PENDING
READY
DELIVERED
```
Do not overload a single sale-status column with every financial and inventory
state.
12.2 Confirm sale
`confirm_sale()` must be transactional and concurrency-safe.
Requirements:
sale is `DRAFT`,
vehicle belongs to company,
customer belongs to company,
vehicle is currently reserved for this sale/customer or is explicitly
allowed for a direct sale,
no other confirmed sale exists for the active ownership cycle,
inventory is locked.
On success:
`Sale.status = CONFIRMED`,
complete linked active reservation,
`VehicleStock.status = SOLD`,
set `sold_at`,
append `InventoryMovement(SALE)`,
issue invoice idempotently or make it immediately available for issuance,
enqueue customer notification after transaction commit.
Notification failure must never roll back a valid sale.
12.3 Cancel sale
Cancellation rules depend on whether:
an invoice exists,
payments exist,
the vehicle was delivered.
Do not delete a confirmed financial transaction.
Use explicit cancellation/reversal services.
If money must be returned, record refunds/reversals in the financial ledger.
---
13. Invoice
Invoice is immutable once issued.
```text
Invoice
- id
- company
- sale                     OneToOne
- number
- issued_on
- due_date
- amount
- currency
- customer_snapshot
- vehicle_snapshot
- created_by
- created_at
```
Number example:
```text
INV-2026-000500
```
Constraints:
```text
UNIQUE(company, number)
UNIQUE(sale)
```
`issue_invoice()` is idempotent and concurrency-safe.
Old invoices must not change because a customer later edits their address or a
vehicle description changes. Snapshot the necessary issued-time data or store a
permanent generated representation.
---
14. Financial accounts
CarFlow must know where money physically resides.
14.1 FinancialAccount
```text
FinancialAccount
- id
- company
- branch                    nullable
- name
- account_type
- currency
- active
- notes
- created_at
```
Types:
```text
CASH
BANK
OTHER
```
Examples:
```text
Kabul AFN Cashbox
Kabul USD Cashbox
Azizi Bank AFN
Azizi Bank USD
Bank of America USD
```
An account has one native currency in the initial architecture.
Balances are computed from ledger entries. Do not store a mutable
`current_balance`.
---
15. Ledger and payments
`LedgerEntry` is the append-only money spine.
15.1 LedgerEntry
Recommended target fields:
```text
LedgerEntry
- id
- company
- entry_type
- amount
- currency
- account -> FinancialAccount
- payment_method
- transaction_date
- description
- reference
- receipt_number
- customer                   nullable
- sale                       nullable
- reservation                nullable
- purchase_order             nullable
- supplier                   nullable/derived where useful
- expense_category           nullable
- reversal_of -> LedgerEntry nullable
- created_by
- created_at
```
Prefer explicit foreign keys for core financial relationships over a
`GenericForeignKey`.
If legacy GFK data exists, migrate it safely.
`entry_type`:
```text
CUSTOMER_PAYMENT
SUPPLIER_PAYMENT
EXPENSE
REFUND
OTHER_IN
OTHER_OUT
```
Direction is derived from entry type.
Example mapping:
```text
CUSTOMER_PAYMENT -> IN
SUPPLIER_PAYMENT -> OUT
EXPENSE          -> OUT
REFUND           -> OUT
OTHER_IN         -> IN
OTHER_OUT        -> OUT
```
All stored amounts are positive.
15.2 Payment methods
Initial enum:
```text
CASH
BANK_TRANSFER
CARD
CHECK
MOBILE_MONEY
OTHER
```
15.3 Customer payment
`record_customer_payment()` records actual money received.
Required information should include:
```text
company
customer
amount
currency
financial account
transaction date
payment method
sale and/or reservation context
created_by
```
Optional:
```text
reference
description
receipt number
```
The payment currency must match the target sale/reservation currency unless an
explicit FX workflow exists.
After commit, CarFlow may send a `payment_recorded` notification.
15.4 Reservation deposit
Deposits are customer payments linked to the reservation and customer.
When a sale is created from that reservation, accounting services include valid
net reservation payments in the sale's paid amount.
Do not duplicate the deposit as a second payment when converting reservation to
sale.
15.5 Sale payment calculations
Never store mutable:
```text
sale.paid_amount
sale.outstanding_amount
```
Derive:
```text
paid = net valid payments allocated/related to sale
     + valid reservation deposits carried into that sale

outstanding = sale.agreed_amount - paid
```
Payment status:
```text
if paid <= 0                 -> UNPAID
if 0 < paid < agreed_amount  -> PARTIAL
if paid >= agreed_amount     -> PAID
```
Business rules should decide whether overpayment is allowed and how it is
represented.
15.6 Supplier payment
Supplier payments must primarily identify what purchase is being paid.
```text
record_supplier_payment(
    purchase_order=...,
    account=...,
    amount=...,
    currency=...,
    ...
)
```
The supplier is derived from `purchase_order.supplier` or redundantly stored
only if a consistency check enforces equality.
This enables:
```text
purchase_order_total
supplier_paid
supplier_outstanding
```
Avoid linking supplier payment only to the supplier when a concrete PO exists.
15.7 Receipts
Every customer payment should have a stable printable reference/receipt number.
Example:
```text
RCT-2026-000182
```
Receipt generation must reference immutable ledger data and must not mutate the
financial record.
---
16. Reversals and corrections
Historical financial rows are never edited or deleted.
Correction:
```text
original entry
      ↑
reversal entry
```
A reversal uses the same:
company,
monetary amount,
currency,
account,
relevant business references,
and points to `reversal_of`.
Accounting calculations subtract the original economic effect.
Database/service rules:
one original entry can be reversed at most once in the normal workflow,
an entry cannot reverse itself,
cross-company reversal is forbidden,
arbitrary reversal trees are forbidden,
use an explicit reinstatement service if restoring a reversed transaction is
ever required,
immutable rows are protected at both Django and database level where
practical.
---
17. Expenses
Operating expenses are money out that are not capitalized into a specific
vehicle's landed cost.
17.1 ExpenseCategory
```text
ExpenseCategory
- id
- company
- name
- code
- active
- created_at
```
Examples:
```text
Rent
Fuel
Marketing
Utilities
Salary
Software
Travel
Bank Fees
Office Supplies
Legal
General
```
17.2 Expense workflow
An expense is still an immutable ledger entry, not a duplicate mutable amount in
another table.
Expense-facing forms capture:
```text
transaction_date
category
amount
currency
financial account
branch
vendor/payee text
reference
description
created_by
```
Then write:
```text
LedgerEntry.entry_type = EXPENSE
```
If an `Expense` wrapper/model is introduced for richer non-financial metadata,
the ledger remains the authoritative money movement.
17.3 Vehicle cost vs operating expense
This distinction is mandatory.
Costs directly attributable to acquiring/preparing a sale vehicle:
```text
purchase price
vehicle shipping
vehicle customs
vehicle inspection
vehicle-specific repair
vehicle-specific storage
vehicle-specific transport
```
belong in `VehicleCostLine`.
General business costs:
```text
office rent
staff salary
marketing
internet
software
office utilities
general travel
general bank fees
```
belong in expenses.
Do not record the same economic cost as both a vehicle cost and an operating
expense unless there is an intentional accounting allocation design.
---
18. Operational accounting and reporting
The `accounting` app calculates reports from authoritative transactional data.
18.1 Cash balance
Per financial account:
```text
account_balance =
net money in - net money out
```
Also aggregate by:
branch,
currency,
account type,
date range.
18.2 Money in / money out
Keep separate from revenue and expense recognition.
```text
MONEY IN != REVENUE
MONEY OUT != BUSINESS EXPENSE
```
A customer may owe money on a sale even when cash has not yet arrived.
A supplier purchase may create a payable before cash leaves the bank.
18.3 Accounts receivable
For confirmed/invoiced sales:
```text
receivable =
sale agreed amount - net customer payments/deposits applied to sale
```
Report:
```text
customer
sale/invoice
due date
currency
amount
paid
outstanding
age
```
Suggested aging:
```text
Current
1-30 days
31-60 days
61-90 days
90+ days
```
18.4 Accounts payable
Per purchase order:
```text
payable =
purchase order total - net supplier payments linked to order
```
Report by:
supplier,
purchase order,
due/aging if added,
branch,
currency.
18.5 Vehicle gross profit
```text
gross_profit =
sale agreed amount - net vehicle landed cost
```
Only compare directly when sale and landed cost are in the same currency or an
explicit FX conversion/reporting policy exists.
```text
gross_margin_percent =
gross_profit / sale agreed amount * 100
```
Do not store these as mutable columns.
18.6 Inventory value
Per currency:
```text
inventory_value =
sum(net landed cost of vehicles still economically in inventory)
```
Define whether `SOLD` but not `DELIVERED` vehicles remain in inventory-value
reports according to business policy; document the policy in tests.
18.7 Recommended dashboard KPIs
Sales:
```text
open leads
qualified leads
lead conversion rate
quotations sent
reservations active
confirmed sales
sales by salesperson
sales by branch
```
Inventory:
```text
available vehicles
reserved vehicles
sold pending delivery
inventory age buckets
vehicles in preparation
inventory value
```
Finance:
```text
cash by account
money in
money out
accounts receivable
accounts payable
customer outstanding
supplier outstanding
gross profit
gross margin
expenses by category
```
---
19. End-to-end sales workflow
Canonical workflow:
```text
LEAD
  │
  ▼
QUALIFIED
  │
  ▼
CUSTOMER
  │
  ▼
QUOTATION
  │
  ▼
ACCEPTED
  │
  ▼
RESERVATION
  │
  ├── optional CUSTOMER PAYMENT / DEPOSIT
  │
  ▼
SALE DRAFT
  │
  ▼
CONFIRMED
  │
  ▼
INVOICE
  │
  ├── PAYMENT #1
  ├── PAYMENT #2
  └── PAYMENT #N
  │
  ▼
PAID / OUTSTANDING
  │
  ▼
READY FOR DELIVERY
  │
  ▼
DELIVERED
```
Example:
```text
Quotation               31,500 USD
Reservation deposit      2,000 USD
Payment #2              15,000 USD
Payment #3               5,000 USD
-----------------------------------
Paid                     22,000 USD
Outstanding               9,500 USD
```
If landed cost is:
```text
25,100 USD
```
then:
```text
Gross profit = 6,400 USD
```
---
20. End-to-end supplier workflow
```text
SELLER / SUPPLIER
       │
       ▼
PURCHASE ORDER
       │
       ├── Vehicle A
       ├── Vehicle B
       └── Vehicle C
       │
       ▼
RECEIVING
       │
       ├── VehicleCostLine(purchase)
       ├── VehicleStock
       └── InventoryMovement(RECEIVE)
       │
       ▼
SUPPLIER PAYMENTS
       │
       ▼
PURCHASE OUTSTANDING / ACCOUNTS PAYABLE
```
Example:
```text
PO total              100,000 USD
Payment #1             20,000 USD
Payment #2             50,000 USD
---------------------------------
Paid                   70,000 USD
Outstanding            30,000 USD
```
---
21. Delivery workflow
A vehicle being sold and a vehicle physically leaving AUTOMEX are different
events.
```text
CONFIRMED SALE
     │
     ▼
VehicleStock = SOLD
     │
     ├── collect remaining payment
     ├── complete paperwork
     └── prepare vehicle
     │
     ▼
READY
     │
     ▼
DELIVER
     │
     ▼
VehicleStock = DELIVERED
delivered_at set
InventoryMovement(DELIVERY)
```
Do not delete the stock row after delivery.
---
22. Documents
`Document` may attach to supported business entities.
At minimum:
```text
Document
- id
- company
- vehicle          nullable
- customer         nullable
- supplier         nullable
- doc_type
- title
- file
- uploaded_by
- created_at
```
If retaining the three-FK design, enforce exactly one target with a database
`CheckConstraint`, not only form validation.
Document target must belong to the same company.
Recommended document types include:
Vehicle:
```text
vehicle_photo
license
sale_document
insurance
customs
inspection
vehicle_document
```
Customer:
```text
customer_photo
tazkera
passport
electricity_bill
other_bill
customer_document
```
Supplier:
```text
supplier_logo
supplier_photo
supplier_license
supplier_document
```
Plus:
```text
other
```
Storage selection is configured in settings; app code uses Django storage APIs.
---
23. Conversation Hub
23.1 Channel
```text
Channel
- id
- company
- type
- provider_account_id
- secret_reference / encrypted credentials strategy
- active
```
Supported types may include:
```text
whatsapp
messenger
instagram
telegram
email
sms
```
Do not store long-lived provider secrets as readable plain JSON when avoidable.
Use external secrets or encryption-at-rest with a key outside PostgreSQL.
23.2 CustomerChannelIdentity
```text
CustomerChannelIdentity
- company
- customer
- channel
- external_id
- created_at
```
Constraint:
```text
UNIQUE(company, channel, external_id)
```
23.3 Conversation
```text
Conversation
- company
- customer
- channel
- external_thread_id
- assigned_to
- status
- last_message_at
```
23.4 Message
```text
Message
- company
- conversation
- direction
- body
- media
- external_message_id
- status
- raw_payload
- created_at
```
Deduplication should be scoped to the provider account/channel:
```text
UNIQUE(channel, external_message_id)
```
where `external_message_id` is populated.
Do not rely on `UNIQUE(company, external_message_id)` across unrelated
providers.
23.5 Inbound webhooks
Flow:
```text
provider webhook
-> verify signature
-> identify exact provider account/channel
-> enqueue raw event
-> return fast success
-> worker parses
-> deduplicates
-> resolves identity/customer
-> creates Message
```
Do not replay every webhook against every active Meta channel.
Resolve the channel from provider identifiers such as page/account/phone-number
IDs before processing.
Unknown sender behavior:
```text
known external identity -> existing customer
unknown external identity -> provisional/new customer + new identity
```
Never silently merge unknown senders.
23.6 Raw payload retention
Raw payloads are useful for troubleshooting but may contain personal data.
Implement a documented retention policy, for example 30-90 days, and redact
secrets/tokens before persistence.
---
24. Notifications
Business code calls only:
```python
notification_engine.notify(
    event=...,
    company=...,
    customer=...,
    context=...,
)
```
Known events may include:
```text
quotation_sent
reservation_created
reservation_expiring
sale_confirmed
payment_recorded
payment_due
vehicle_ready
vehicle_delivered
```
Sending is best-effort and must not invalidate the underlying business
transaction.
Use `transaction.on_commit()` before enqueueing notifications generated by a
database transaction.
Disabled adapters create a clear skipped status and do not crash business code.
---
25. Multi-tenancy details
25.1 TenantModel
Abstract base:
```text
company -> Organization (PROTECT)
objects -> fail-closed TenantManager
all_objects -> explicit unfiltered manager
```
`TenantManager.get_queryset()`:
```text
tenant context present -> filter company
tenant context missing -> raise NoTenantContext
```
Do not return all rows by default when context is absent.
25.2 Cross-tenant relationship integrity
Every service must validate same-company relationships.
Examples:
```text
Sale.company == Sale.customer.company
Sale.company == Sale.vehicle.company
Reservation.company == Reservation.vehicle.company
PurchaseOrder.company == PurchaseOrder.supplier.company
VehicleStock.company == VehicleStock.vehicle.company
Conversation.company == Conversation.customer.company
Conversation.company == Conversation.channel.company
Document.company == attached target.company
LedgerEntry.company == referenced business objects.company
```
Use database-level enforcement where practical for the highest-risk
relationships.
---
26. Concurrency rules
Critical workflows must be tested under concurrent PostgreSQL transactions.
Reservation
Two users cannot reserve one vehicle.
Use:
```python
select_for_update()
```
or an atomic conditional update plus database uniqueness.
Sale
Two sales cannot confirm against the same available ownership cycle.
Lock the stock/reservation rows.
Invoice
Two requests cannot issue two invoices for one sale.
Use `OneToOneField` / unique DB constraint and transactional idempotency.
Receiving
Two workers cannot receive the same PO/line twice.
Use row locks and idempotency constraints.
Reversal
Two users cannot reverse the same ledger/cost entry twice.
Use uniqueness on `reversal_of`.
---
27. Audit
Use `django-simple-history` for mutable business records such as:
```text
Vehicle
VehicleStock
InventoryLocation
Supplier
PurchaseOrder
Customer
Lead
Quotation
Reservation
Sale
```
Include inventory movements as explicit event history.
Immutable rows such as:
```text
LedgerEntry
VehicleCostLine
Invoice
```
do not need ordinary edit history because they are append-only, but their
creation user/time and reversal relationships must be preserved.
---
28. Database constraints checklist
Coding agents must implement these or equivalent protections where supported.
Identity
```text
Vehicle: UNIQUE(company, vin)
Branch: UNIQUE(company, name)
Quotation: UNIQUE(company, number)
Invoice: UNIQUE(company, number)
Invoice: UNIQUE(sale)
```
Workflow
```text
Reservation: max one ACTIVE reservation per vehicle
LedgerEntry: max one normal reversal per original entry
VehicleCostLine: max one normal reversal per original entry
Message: UNIQUE(channel, external_message_id) when populated
CustomerChannelIdentity: UNIQUE(company, channel, external_id)
VehicleStock: OneToOne(vehicle)
```
Documents
Exactly one document target if using the multi-FK design.
Money
```text
amount > 0
currency is valid
account currency == ledger currency
```
unless a dedicated FX workflow is introduced.
---
29. Service-layer boundaries
Views should be thin.
Business mutations belong in domain services, for example:
```text
purchases/services.py
- receive_order(...)
- add_vehicle_cost(...)
- reverse_vehicle_cost(...)

inventory/services.py
- receive_vehicle(...)
- transfer_vehicle(...)
- move_vehicle(...)
- start_inspection(...)
- mark_available(...)
- release_reservation(...)
- deliver_vehicle(...)

sales/services.py
- convert_lead(...)
- create_reservation(...)
- expire_reservation(...)
- cancel_reservation(...)
- confirm_sale(...)
- cancel_sale(...)
- issue_invoice(...)

payments/services.py
- record_customer_payment(...)
- record_supplier_payment(...)
- record_expense(...)
- reverse_entry(...)

accounting/services.py
- account_balance(...)
- money_in(...)
- money_out(...)
- sale_payments(...)
- sale_outstanding(...)
- purchase_payments(...)
- purchase_outstanding(...)
- accounts_receivable(...)
- accounts_payable(...)
- vehicle_gross_profit(...)
- inventory_value(...)
```
Do not hide major business mutations in model `save()` signals.
Explicit services are easier to reason about, test, and make transactional.
---
30. Data integrity vs cached/derived fields
Do not persist derived monetary values merely for convenience.
Derived:
```text
vehicle landed cost
sale paid amount
sale outstanding
purchase paid amount
purchase outstanding
financial account balance
gross profit
gross margin
inventory age
AR/AP totals
```
If performance later requires materialized/cached values, introduce them only
with:
clear ownership,
invalidation strategy,
reconciliation tests,
ability to recompute from authoritative events.
---
31. Technology stack
Layer	Technology
Language / framework	Python 3.12 · Django 5.2 LTS
Frontend	Django Templates + Tailwind CSS
Database	PostgreSQL 16
Cache / broker	Redis 7
Async	Celery + Celery Beat
App server	Gunicorn
Reverse proxy	Nginx
Storage	Django storage API; local / S3-compatible
Audit	`django-simple-history`
Testing	pytest · pytest-django · factory_boy
---
32. Docker architecture
One app image, three roles:
```text
web     -> Gunicorn
worker  -> Celery worker
beat    -> Celery Beat
```
Only one controlled deployment step should run migrations.
Do not rely on multiple replicas simultaneously invoking `migrate`.
Services:
```text
nginx
web
worker
beat
postgres
redis
```
Development may use Django's development server and bind-mounted source.
---
33. Repository layout
Recommended structure:
```text
car-flow/
├── apps/
│   ├── core/
│   ├── organizations/
│   ├── branches/
│   ├── accounts/
│   ├── suppliers/
│   ├── vehicles/
│   ├── purchases/
│   ├── inventory/
│   ├── customers/
│   ├── sales/
│   ├── payments/
│   ├── expenses/
│   ├── accounting/
│   ├── documents/
│   ├── communications/
│   └── audit/
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   ├── test.py
│   │   └── prod.py
│   ├── urls.py
│   ├── celery.py
│   └── checks.py
├── docker/
│   ├── web/Dockerfile
│   ├── entrypoint.sh
│   └── nginx/nginx.conf
├── locale/
├── requirements/
├── scripts/
├── static/
├── templates/
├── docker-compose.yml
├── docker-compose.override.yml
├── .env.example
├── pytest.ini
├── README.md
├── PRODUCTION.md
└── agent.md
```
---
34. Quick start
Example development workflow:
```bash
git clone <repository-url>
cd car-flow

cp .env.example .env
docker compose up --build
```
Minimum environment configuration:
```text
DJANGO_SECRET_KEY=<strong random value>
DB_PASSWORD=<private password>

all *_ENABLED provider flags = False
provider credentials = blank
```
Verify:
```bash
curl -I http://localhost:8000/accounts/login/
```
Production should be served through TLS and Nginx/Gunicorn.
---
35. Configuration contract
All secrets/config are environment-driven.
Core:
```text
DJANGO_SECRET_KEY
DJANGO_DEBUG
DJANGO_ALLOWED_HOSTS
DJANGO_CSRF_TRUSTED_ORIGINS
DJANGO_SETTINGS_MODULE
```
Database:
```text
DB_NAME
DB_USER
DB_PASSWORD
DB_HOST
DB_PORT
```
Redis/Celery:
```text
REDIS_URL
CELERY_BROKER_URL
CELERY_RESULT_BACKEND
```
Storage:
```text
S3_ENABLED
S3_ENDPOINT_URL
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
S3_BUCKET_NAME
```
Integrations must have:
```text
<PROVIDER>_ENABLED=False
```
by default.
A Django system check must reject an enabled integration with missing required
credentials.
---
36. Security
Minimum production requirements:
HTTPS.
Secure session and CSRF cookies.
`DEBUG=False`.
Strict `ALLOWED_HOSTS`.
CSRF trusted origins configured.
`X-Frame-Options` or CSP frame policy.
Content-type sniffing protection.
Secrets excluded from Git.
Super Admin only in Django Admin.
Least-privilege role permissions.
Tenant fail-closed manager.
Same-company relationship validation.
File upload validation.
Provider webhook signature verification.
Rate limiting on sensitive public endpoints where appropriate.
Database backups.
S3 bucket/private media policy where applicable.
No plaintext tenant provider secrets if avoidable.
---
37. Testing strategy
Fast tests are useful, but PostgreSQL integration tests are mandatory for
critical invariants.
37.1 Unit tests
Cover:
```text
service validation
status transitions
accounting calculations
permission checks
money/currency validation
notification adapter selection
```
37.2 PostgreSQL integration tests
Mandatory cases:
```text
two users reserve same vehicle
two users confirm sale against same vehicle
two requests issue invoice simultaneously
two users reverse same payment simultaneously
two workers receive same PO
cross-tenant FK/reference attempt
tenant manager without context
duplicate provider webhook
reservation expiry release
deposit carried into sale once
supplier payment updates correct PO outstanding
vehicle-cost reversal changes landed cost correctly
document exactly-one-target DB constraint
```
Do not rely only on SQLite for transaction, locking, partial-unique, JSON, or
PostgreSQL-specific constraint behavior.
37.3 Required invariant gates
CI must fail if:
integrations-off boot fails,
tenant isolation fails,
immutable monetary rows can be edited/deleted,
duplicate active reservation is possible,
duplicate invoice for sale is possible,
duplicate reversal is possible,
accounting net calculations disagree with ledger events.
---
38. Internationalization and RTL
Supported:
```text
en   English
prs  Dari
ps   Pashto
```
Dari and Pashto render RTL.
Rules:
every user-facing server-rendered string is translatable,
use logical Tailwind/CSS properties (`ms-*`, `me-*`, `text-start`,
`text-end`) instead of hard-coded left/right where possible,
user language preference persists,
`<html lang="..." dir="...">` must be correct.
Typical catalog flow:
```bash
python manage.py makemessages -l en -l prs -l ps
python manage.py compilemessages
```
---
39. Observability
Development:
```text
Docker logs
Django logs
Celery logs
PostgreSQL health
Redis health
```
Production recommendation:
```text
structured JSON logs
Sentry (errors)
metrics (Prometheus-compatible or equivalent)
dashboarding (Grafana or equivalent)
Celery task failure monitoring
database health/backup alerts
```
Financial/business service failures should log:
```text
company
user
operation
business object IDs
correlation/request ID
```
without leaking credentials or sensitive payloads.
---
40. Backups
Back up both:
PostgreSQL.
Media/object storage.
A database backup without vehicle/customer documents is incomplete.
Example PostgreSQL backup:
```bash
docker compose exec -T db \
  pg_dump -U carflow -d carflow > backup_$(date +%F).sql
```
Test restore procedures periodically.
Production backup policy should define:
```text
frequency
retention
encryption
offsite copy
restore test schedule
RPO
RTO
```
---
41. Migration guidance for coding agents
The existing implementation may still reflect the older architecture.
Agents must make incremental migrations; do not destructively reset production
data.
Recommended order:
Phase 1 — integrity foundation
Make tenant manager fail closed.
Add same-company service validation.
Add DB constraints for:
one invoice per sale,
one active reservation per vehicle,
one reversal per original ledger entry,
document exactly one target.
Add PostgreSQL concurrency tests.
Phase 2 — inventory redesign
Add `InventoryLocation`.
Add `InventoryMovement`.
Expand/migrate `VehicleStock`.
Make `VehicleStock` the authoritative inventory state.
Remove/deprecate overlapping availability state from `Vehicle`.
Update purchasing/reservation/sale services.
Phase 3 — financial account/payment redesign
Add `FinancialAccount`.
Add `transaction_date`, payment method, account, reference, receipt number.
Replace/migrate core GFK payment relationships with explicit references.
Link supplier payment to `PurchaseOrder`.
Support reservation deposits as true payments.
Protect immutable ledger rows at DB level.
Prevent duplicate reversals.
Phase 4 — landed-cost correction
Add `reversal_of` to `VehicleCostLine`.
Migrate cost calculation to net events.
Protect cost rows at DB level.
Add reversal tests.
Phase 5 — CRM/sales improvements
Add lead assignment and lost reason.
Add `LeadActivity`.
Add quotation number/revision approach.
Add reservation expiry.
Split commercial/payment/delivery state semantics.
Add invoice due date and snapshots.
Phase 6 — reporting
Add:
```text
account balances
AR
AP
vehicle gross profit
gross margin
inventory aging
inventory value
expense-by-category
salesperson/branch performance
```
Every phase must include migrations and tests.
---
42. Coding-agent rules
These rules are mandatory.
Do not rewrite unrelated modules while implementing one feature.
Do not delete historical business/financial data to simplify a migration.
Write data migrations when semantics change.
Use PostgreSQL constraints for critical invariants.
Use transactions for multi-row business changes.
Use row locks/atomic conditional writes for concurrency-sensitive flows.
Never trust client-provided tenant IDs.
Never silently convert currency.
Never store derived balances/profits as authoritative fields.
Never update/delete immutable financial/cost records.
Never treat a reservation deposit amount field as an actual payment.
Never record supplier payment without its PO when the PO is known.
Never duplicate one economic event as both vehicle cost and general
expense without an intentional allocation rule.
Never send provider API calls directly from sales/payments/purchases.
Enqueue non-critical notifications only after DB commit.
Never rely on form validation for critical database invariants.
Keep views thin; business mutations belong in services.
Add tests for every new state transition and constraint.
Preserve English/Dari/Pashto and RTL compatibility.
Update this README and migrations together when architecture changes.
---
43. Definition of done for a business feature
A feature is not complete when only the UI works.
It is complete when:
model/schema is correct,
tenant rules are enforced,
permissions are enforced,
service API exists,
transaction/concurrency behavior is correct,
database constraints exist where needed,
audit/immutability behavior is correct,
translations are supported,
tests exist,
PostgreSQL integration tests pass where applicable,
failure behavior is defined,
documentation is updated.
---
44. Final target workflow
```text
                           AUTOMEX CARFLOW

SELLER / SUPPLIER
       │
       ▼
PURCHASE ORDER
       │
       ├────────► SUPPLIER PAYMENTS ─────► ACCOUNTS PAYABLE
       │
       ▼
VEHICLE ACQUISITION
       │
       ▼
LANDED COST EVENTS
       │
       ▼
RECEIVING
       │
       ▼
INVENTORY
       │
       ├── Location
       ├── Movement History
       ├── Inspection
       ├── Preparation
       └── Available
       │
       ▼
LEAD / CUSTOMER
       │
       ▼
QUOTATION
       │
       ▼
RESERVATION
       │
       ├────────► DEPOSIT / PAYMENT
       │
       ▼
SALE
       │
       ▼
INVOICE
       │
       ├────────► CUSTOMER PAYMENTS ─────► ACCOUNTS RECEIVABLE
       │
       ▼
SOLD / READY
       │
       ▼
DELIVERED
       │
       ▼
VEHICLE GROSS PROFIT

GENERAL OPERATING EXPENSES
       │
       ▼
FINANCIAL LEDGER
       │
       ▼
FINANCIAL ACCOUNTS
       │
       ▼
CASH / BANK POSITION

ALL AUTHORITATIVE EVENTS
       │
       ▼
ACCOUNTING & MANAGEMENT REPORTING
```
The central design objective is simple:
> Every important business question must be answerable from traceable,
> tenant-safe, transactionally correct source data without manually fixing
> conflicting status or balance fields.
Examples:
```text
Who did we buy this vehicle from?
What did this vehicle really cost?
Where is the vehicle now?
Where has it been?
Who is it reserved for?
How much has the customer paid?
How much does the customer still owe?
Which bank/cashbox received the money?
How much do we still owe the supplier for this PO?
What did we spend on general operations?
What was the gross profit on this vehicle?
Who changed the business record?
What financial correction reversed the original entry?
```
CarFlow should answer all of these directly from its authoritative data model.