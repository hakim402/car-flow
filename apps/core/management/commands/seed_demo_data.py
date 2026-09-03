"""Create a coherent, repeatable CarFlow dataset for local UI testing."""

from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.branches.models import Branch
from apps.communications.models import (
    Channel,
    ChannelType,
    Conversation,
    ConversationStatus,
    CustomerChannelIdentity,
    Message,
    MessageDirection,
    MessageStatus,
    Notification,
    NotificationChannel,
    NotificationDeliveryLog,
    NotificationEvent,
    NotificationPreference,
    NotificationStatus,
)
from apps.core.tenancy import company_scope
from apps.customers.models import Customer
from apps.documents.models import Document, DocumentType
from apps.expenses.models import ExpenseCategory
from apps.expenses.services import record_expense
from apps.financing.models import (
    AgreementGuarantor,
    AgreementStatus,
    AgreementType,
    FinanceAgreement,
    FinancingPartner,
    InstallmentReminder,
    PaymentFrequency,
)
from apps.financing.services import (
    approve_agreement,
    initialize_agreement,
    record_installment_payment,
    record_lender_disbursement,
    submit_agreement,
)
from apps.inventory.models import LocationType, StockStatus, VehicleCondition
from apps.inventory.services import adjust_stock_status, receive_vehicle, reserve_stock
from apps.organizations.models import Organization
from apps.payments.models import EntryType, FinancialAccount, LedgerEntry, PaymentMethod
from apps.payments.services import record_payment, record_supplier_payment
from apps.purchases.models import (
    CostType,
    Incoterms,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseStatus,
    PurchaseType,
    ShippingMethod,
    VehicleCostLine,
)
from apps.sales.models import (
    Lead,
    LeadSource,
    LeadStatus,
    Quotation,
    QuotationStatus,
    Reservation,
    ReservationStatus,
    Sale,
    SaleStatus,
)
from apps.sales.services import complete_sale, issue_invoice
from apps.suppliers.models import Supplier, SupplierKind, SupplierType
from apps.vehicles.models import BodyType, DriveType, FuelType, TransmissionType, Vehicle


DEMO_PREFIX = "CF-DEMO"


class Command(BaseCommand):
    help = "Seed realistic, idempotent demo data for a company without deleting existing rows."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, help="Company/organization primary key.")
        parser.add_argument("--count", type=int, default=20, help="Number of demo business cycles.")

    def handle(self, *args, **options):
        count = options["count"]
        if count < 1 or count > 100:
            raise CommandError("--count must be between 1 and 100.")
        companies = Organization.objects.all()
        if options["company_id"]:
            company = companies.filter(pk=options["company_id"]).first()
            if company is None:
                raise CommandError("The requested company does not exist.")
        elif companies.count() == 1:
            company = companies.first()
        else:
            raise CommandError("Pass --company-id when the database contains multiple companies.")

        user = User.objects.filter(company=company, is_active=True).order_by("pk").first()
        if user is None:
            raise CommandError("Create an active company user before seeding demo data.")

        with transaction.atomic(), company_scope(company):
            self._seed(company, user, count)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready for {company.name}: {count} complete business cycles."
            )
        )

    def _seed(self, company, user, count):
        today = timezone.localdate()
        now = timezone.now()
        branch_names = ["Kabul Main", "Kabul West", "Herat", "Mazar-e-Sharif"]
        branches = [
            Branch.objects.get_or_create(company=company, name=name)[0]
            for name in branch_names
        ]

        notification_events = []
        for index in range(1, count + 1):
            event, _ = NotificationEvent.objects.get_or_create(
                key=f"demo_follow_up_{index:03d}",
                defaults={
                    "label": f"Demo follow-up {index}",
                    "description": "Seeded notification event for UI verification.",
                    "default_template": "A customer follow-up requires attention.",
                },
            )
            notification_events.append(event)

        channel_types = list(ChannelType.values)
        channels = []
        for index in range(1, count + 1):
            marker = f"{DEMO_PREFIX}-CHANNEL-{index:03d}"
            channel = Channel.objects.filter(credentials__demo_marker=marker).first()
            if channel is None:
                channel = Channel.objects.create(
                    company=company,
                    type=channel_types[(index - 1) % len(channel_types)],
                    credentials={"demo_marker": marker},
                    active=index % 5 != 0,
                )
            channels.append(channel)

        partners = []
        for index in range(1, count + 1):
            partner, _ = FinancingPartner.objects.get_or_create(
                company=company,
                name=f"Demo Finance Partner {index:02d}",
                defaults={
                    "partner_type": (
                        FinancingPartner.PartnerType.BANK
                        if index % 2
                        else FinancingPartner.PartnerType.MICROFINANCE
                    ),
                    "phone": f"+9379002{index:04d}",
                    "email": f"finance{index:02d}@demo.carflow.test",
                    "notes": "Local demo financing partner.",
                },
            )
            partners.append(partner)

        locations = []
        accounts = []
        categories = []
        for index in range(1, count + 1):
            branch = branches[(index - 1) % len(branches)]
            location, _ = branch.locations.get_or_create(
                company=company,
                code=f"D{index:03d}",
                defaults={
                    "name": f"Demo Lot {index:02d}",
                    "type": list(LocationType.values)[(index - 1) % len(LocationType.values)],
                    "active": True,
                },
            )
            locations.append(location)
            account, _ = FinancialAccount.objects.get_or_create(
                company=company,
                name=f"Demo USD {'Cashbox' if index % 2 else 'Bank'} {index:02d}",
                defaults={
                    "branch": branch,
                    "account_type": (
                        FinancialAccount.AccountType.CASH
                        if index % 2
                        else FinancialAccount.AccountType.BANK
                    ),
                    "currency": "USD",
                    "notes": "Seeded account for live workflow testing.",
                },
            )
            accounts.append(account)
            category, _ = ExpenseCategory.objects.get_or_create(
                company=company,
                name=f"Demo Expense Category {index:02d}",
                defaults={"code": f"DEX-{index:03d}", "active": True},
            )
            categories.append(category)

        makes = ["Toyota", "Honda", "Hyundai", "Kia", "Nissan", "Ford"]
        models = ["Corolla", "Civic", "Elantra", "Sportage", "Sunny", "Ranger"]
        supplier_types = list(SupplierType.values)
        sources = list(LeadSource.values)

        for index in range(1, count + 1):
            branch = branches[(index - 1) % len(branches)]
            location = locations[index - 1]
            account = accounts[index - 1]
            category = categories[index - 1]
            partner = partners[index - 1]
            channel = channels[index - 1]

            supplier, _ = Supplier.objects.get_or_create(
                company=company,
                name=f"Demo Supplier {index:02d}",
                defaults={
                    "kind": SupplierKind.BUSINESS if index % 3 else SupplierKind.INDIVIDUAL,
                    "supplier_type": supplier_types[(index - 1) % len(supplier_types)],
                    "national_id": f"SUP-DEMO-{index:04d}",
                    "country": "AF" if index % 2 else "JP",
                    "contact_person": f"Supplier Contact {index:02d}",
                    "phone": f"+9378001{index:04d}",
                    "email": f"supplier{index:02d}@demo.carflow.test",
                    "address": f"Demo trade district {index}, Afghanistan",
                },
            )
            customer, _ = Customer.objects.get_or_create(
                company=company,
                national_id=f"CUS-DEMO-{index:04d}",
                defaults={
                    "full_name": f"Demo Customer {index:02d}",
                    "phone": f"+9377000{index:04d}",
                    "email": f"customer{index:02d}@demo.carflow.test",
                    "branch": branch,
                    "notes": "Seeded customer for sales, finance, and messaging UI checks.",
                    "created_by": user,
                },
            )

            sold_vehicle = self._vehicle(company, branch, index, makes, models, sold=True)
            stock_vehicle = self._vehicle(company, branch, index, makes, models, sold=False)
            sale_price = Decimal("17500.00") + Decimal(index * 425)
            purchase_price = sale_price - Decimal("3500.00")

            order, _ = PurchaseOrder.objects.get_or_create(
                company=company,
                reference=f"{DEMO_PREFIX}-PO-{index:03d}",
                defaults={
                    "supplier": supplier,
                    "branch": branch,
                    "status": PurchaseStatus.RECEIVED,
                    "purchase_type": PurchaseType.IMPORT if index % 2 == 0 else PurchaseType.DOMESTIC,
                    "order_date": today - timedelta(days=150 - index),
                    "origin_country": "JP" if index % 2 == 0 else "AF",
                    "incoterms": Incoterms.CIF if index % 2 == 0 else "",
                    "shipping_method": ShippingMethod.CONTAINER if index % 2 == 0 else ShippingMethod.LAND,
                    "bill_of_lading_no": f"BL-DEMO-{index:04d}" if index % 2 == 0 else "",
                    "container_no": f"CONT-DEMO-{index:04d}" if index % 2 == 0 else "",
                    "shipped_date": today - timedelta(days=120 - index) if index % 2 == 0 else None,
                    "eta": today - timedelta(days=90 - index) if index % 2 == 0 else None,
                    "notes": "Completed demo acquisition.",
                    "created_by": user,
                },
            )
            for vehicle, suffix, amount in (
                (sold_vehicle, "S", purchase_price),
                (stock_vehicle, "I", purchase_price - Decimal("1200.00")),
            ):
                PurchaseOrderLine.objects.get_or_create(
                    order=order,
                    vehicle=vehicle,
                    defaults={
                        "description": f"Demo vehicle {index:02d}-{suffix}",
                        "amount": amount,
                        "currency": "USD",
                    },
                )
                VehicleCostLine.objects.get_or_create(
                    company=company,
                    vehicle=vehicle,
                    cost_type=CostType.PURCHASE,
                    description=f"{DEMO_PREFIX} purchase {index:03d}-{suffix}",
                    defaults={"amount": amount, "currency": "USD", "created_by": user},
                )

            sold_stock = receive_vehicle(
                sold_vehicle, branch, user=user, location=location,
                notes=f"{DEMO_PREFIX} received for sales flow",
                condition=VehicleCondition.GOOD,
            )
            if sold_stock.status == StockStatus.RECEIVED:
                sold_stock = adjust_stock_status(
                    sold_stock, StockStatus.AVAILABLE, user=user, notes="Demo preparation complete"
                )
            inventory_stock = receive_vehicle(
                stock_vehicle, branch, user=user, location=location,
                notes=f"{DEMO_PREFIX} inventory vehicle",
                condition=list(VehicleCondition.values)[(index - 1) % len(VehicleCondition.values)],
            )
            desired_status = [
                StockStatus.RECEIVED,
                StockStatus.INSPECTION,
                StockStatus.PREPARATION,
                StockStatus.AVAILABLE,
            ][(index - 1) % 4]
            if inventory_stock.status == StockStatus.RECEIVED and desired_status != StockStatus.RECEIVED:
                adjust_stock_status(
                    inventory_stock, desired_status, user=user, notes="Demo inventory lifecycle"
                )

            lead, _ = Lead.objects.get_or_create(
                company=company,
                name=f"Demo Lead {index:02d}",
                defaults={
                    "phone": customer.phone,
                    "customer": customer,
                    "vehicle_of_interest": sold_vehicle,
                    "source": sources[(index - 1) % len(sources)],
                    "status": LeadStatus.CONVERTED,
                    "branch": branch,
                    "assigned_to": user,
                    "notes": "Converted demo opportunity.",
                    "created_by": user,
                },
            )
            quotation, _ = Quotation.objects.get_or_create(
                company=company,
                number=f"{DEMO_PREFIX}-QT-{index:03d}",
                defaults={
                    "customer": customer,
                    "vehicle": sold_vehicle,
                    "lead": lead,
                    "amount": sale_price,
                    "currency": "USD",
                    "valid_until": today + timedelta(days=15),
                    "status": QuotationStatus.ACCEPTED,
                    "notes": "Accepted demo quotation.",
                    "created_by": user,
                },
            )
            reservation = Reservation.objects.filter(
                company=company, quotation=quotation
            ).first()
            if reservation is None:
                reserve_stock(sold_vehicle, user=user, notes="Demo customer reservation")
                reservation = Reservation.objects.create(
                    company=company,
                    customer=customer,
                    vehicle=sold_vehicle,
                    quotation=quotation,
                    deposit_amount=Decimal("2500.00") + Decimal(index * 25),
                    currency="USD",
                    expires_at=now + timedelta(days=7),
                    status=ReservationStatus.ACTIVE,
                    notes="Demo reservation converted to a sale.",
                    created_by=user,
                )
            sale, _ = Sale.objects.get_or_create(
                company=company,
                vehicle=sold_vehicle,
                defaults={
                    "customer": customer,
                    "reservation": reservation,
                    "agreed_amount": sale_price,
                    "currency": "USD",
                    "sale_date": today - timedelta(days=count - index),
                    "status": SaleStatus.DRAFT,
                    "notes": "Demo credit sale with an unpaid balance.",
                    "created_by": user,
                },
            )
            if sale.status == SaleStatus.DRAFT:
                complete_sale(sale, user=user)
                sale.refresh_from_db()
            issue_invoice(sale, user=user)

            down_payment = (sale_price * Decimal("0.30")).quantize(Decimal("0.01"))
            down_reference = f"{DEMO_PREFIX}-DOWN-{index:03d}"
            if not LedgerEntry.objects.filter(reference=down_reference).exists():
                record_payment(
                    sale,
                    down_payment,
                    "USD",
                    user=user,
                    account=account,
                    payment_method=PaymentMethod.CASH if index % 2 else PaymentMethod.BANK_TRANSFER,
                    transaction_date=today - timedelta(days=count - index),
                    reference=down_reference,
                    description="Demo customer down payment",
                )

            agreement = FinanceAgreement.objects.filter(
                company=company, number=f"{DEMO_PREFIX}-FIN-{index:03d}"
            ).first()
            if agreement is None:
                agreement_type = (
                    AgreementType.DEALER_INSTALLMENT
                    if index % 2
                    else AgreementType.EXTERNAL_LENDER
                )
                agreement = FinanceAgreement(
                    company=company,
                    number=f"{DEMO_PREFIX}-FIN-{index:03d}",
                    sale=sale,
                    branch=branch,
                    agreement_type=agreement_type,
                    partner=partner if agreement_type == AgreementType.EXTERNAL_LENDER else None,
                    external_reference=f"LENDER-DEMO-{index:04d}" if index % 2 == 0 else "",
                    currency="USD",
                    cash_price=sale_price,
                    markup_amount=Decimal("0.00"),
                    down_payment_required=down_payment,
                    installment_count=4,
                    frequency=PaymentFrequency.MONTHLY,
                    first_due_date=today - timedelta(days=65 - index * 2),
                    grace_days=5,
                    notes="Seeded agreement for installment and overdue UI testing.",
                )
                initialize_agreement(agreement, user=user)
                submit_agreement(agreement, user=user)
                approve_agreement(agreement, user=user)
                agreement.refresh_from_db()

            AgreementGuarantor.objects.get_or_create(
                company=company,
                agreement=agreement,
                national_id=f"GUA-DEMO-{index:04d}",
                defaults={
                    "full_name": f"Demo Guarantor {index:02d}",
                    "phone": f"+9376003{index:04d}",
                    "address": f"Demo guarantor address {index}",
                },
            )
            first_installment = agreement.installments.order_by("sequence").first()
            if first_installment:
                InstallmentReminder.objects.get_or_create(
                    company=company,
                    installment=first_installment,
                    kind="demo_review",
                    reminder_date=today,
                )

            finance_reference = f"{DEMO_PREFIX}-FINPAY-{index:03d}"
            if agreement.status == AgreementStatus.ACTIVE and not LedgerEntry.objects.filter(
                reference=finance_reference
            ).exists():
                financed_payment = (agreement.amount_financed * Decimal("0.18")).quantize(
                    Decimal("0.01")
                )
                if agreement.agreement_type == AgreementType.DEALER_INSTALLMENT:
                    record_installment_payment(
                        agreement,
                        financed_payment,
                        account,
                        user=user,
                        payment_method=PaymentMethod.CASH,
                        transaction_date=today,
                        reference=finance_reference,
                        description="Demo installment collection",
                    )
                else:
                    record_lender_disbursement(
                        agreement,
                        financed_payment,
                        account,
                        user=user,
                        payment_method=PaymentMethod.BANK_TRANSFER,
                        transaction_date=today,
                        reference=finance_reference,
                        description="Demo partial lender disbursement",
                    )

            supplier_reference = f"{DEMO_PREFIX}-SUPPAY-{index:03d}"
            if not LedgerEntry.objects.filter(reference=supplier_reference).exists():
                record_supplier_payment(
                    supplier,
                    purchase_price * Decimal("0.55"),
                    "USD",
                    user=user,
                    purchase_order=order,
                    account=account,
                    payment_method=PaymentMethod.BANK_TRANSFER,
                    transaction_date=today - timedelta(days=40),
                    reference=supplier_reference,
                    description="Demo supplier part-payment",
                )
            expense_reference = f"{DEMO_PREFIX}-EXP-{index:03d}"
            if not LedgerEntry.objects.filter(reference=expense_reference).exists():
                record_expense(
                    company,
                    Decimal("45.00") + Decimal(index * 7),
                    "USD",
                    description=f"Demo operating expense {index:02d}",
                    user=user,
                    category=category,
                    account=account,
                    branch=branch,
                    vendor=f"Demo Vendor {index:02d}",
                    reference=expense_reference,
                    transaction_date=today - timedelta(days=index % 15),
                )

            identity, _ = CustomerChannelIdentity.objects.get_or_create(
                company=company,
                channel=channel,
                external_id=f"{DEMO_PREFIX}-CONTACT-{index:03d}",
                defaults={"customer": customer},
            )
            conversation, _ = Conversation.objects.get_or_create(
                company=company,
                channel=channel,
                external_thread_id=f"{DEMO_PREFIX}-THREAD-{index:03d}",
                defaults={
                    "customer": identity.customer,
                    "assigned_to": user,
                    "status": ConversationStatus.OPEN if index % 4 else ConversationStatus.CLOSED,
                    "last_message_at": now - timedelta(hours=index),
                },
            )
            for direction, suffix, body in (
                (MessageDirection.IN, "IN", "Is this vehicle still available on installments?"),
                (MessageDirection.OUT, "OUT", "Yes. Your payment schedule is ready for review."),
            ):
                Message.objects.get_or_create(
                    company=company,
                    external_message_id=f"{DEMO_PREFIX}-MSG-{index:03d}-{suffix}",
                    defaults={
                        "conversation": conversation,
                        "direction": direction,
                        "body": body,
                        "status": MessageStatus.READ if direction == MessageDirection.IN else MessageStatus.SENT,
                        "raw_payload": {"demo": True, "sequence": index},
                    },
                )

            event = notification_events[index - 1]
            preference, _ = NotificationPreference.objects.get_or_create(
                company=company,
                user=user,
                event=event,
                defaults={"enabled": True, "email": False, "in_app": True},
            )
            notification, _ = Notification.objects.get_or_create(
                company=company,
                recipient=user,
                event=event,
                title=f"Demo follow-up #{index:02d}",
                defaults={
                    "message": f"Review {customer.full_name}'s outstanding finance balance.",
                    "channel": NotificationChannel.IN_APP,
                    "status": NotificationStatus.READ if index % 3 == 0 else NotificationStatus.SENT,
                    "sent_at": now - timedelta(hours=index),
                    "read_at": now - timedelta(hours=index - 1) if index % 3 == 0 else None,
                    "metadata": {"demo": True, "sale_id": sale.pk},
                },
            )
            NotificationDeliveryLog.objects.get_or_create(
                notification=notification,
                channel=NotificationChannel.IN_APP,
                defaults={
                    "status": notification.status,
                    "provider_response": "Local demo delivery",
                },
            )

            document_title = f"{DEMO_PREFIX} vehicle record {index:03d}"
            if not Document.objects.filter(title=document_title).exists():
                document = Document(
                    company=company,
                    vehicle=sold_vehicle,
                    doc_type=DocumentType.VEHICLE_DOCUMENT,
                    title=document_title,
                    uploaded_by=user,
                )
                document.file.save(
                    f"carflow-demo-record-{index:03d}.txt",
                    ContentFile(
                        f"CarFlow demo document {index}\nVehicle: {sold_vehicle.vin}\n".encode()
                    ),
                    save=False,
                )
                document.save()

    def _vehicle(self, company, branch, index, makes, models, *, sold):
        sequence = index if sold else index + 1000
        vin = f"CF26{sequence:013d}"
        vehicle, _ = Vehicle.objects.get_or_create(
            company=company,
            vin=vin,
            defaults={
                "plate_number": f"KBL-{sequence:05d}",
                "registration_number": f"REG-DEMO-{sequence:05d}",
                "engine_number": f"ENG-DEMO-{sequence:05d}",
                "chassis_number": vin,
                "make": makes[(index - 1) % len(makes)],
                "model": models[(index - 1) % len(models)],
                "model_variant": "Premium" if index % 2 else "Standard",
                "year": 2017 + index % 9,
                "color": ["White", "Black", "Silver", "Blue"][(index - 1) % 4],
                "mileage": 18000 + index * 2750,
                "body_type": list(BodyType.values)[(index - 1) % len(BodyType.values)],
                "fuel_type": list(FuelType.values)[(index - 1) % len(FuelType.values)],
                "transmission": list(TransmissionType.values)[(index - 1) % len(TransmissionType.values)],
                "drive_type": list(DriveType.values)[(index - 1) % len(DriveType.values)],
                "door_count": 4,
                "seating_capacity": 5,
                "country_of_origin": "JP" if index % 2 else "KR",
                "branch": branch,
                "notes": "Seeded vehicle for responsive UI and workflow verification.",
            },
        )
        return vehicle
