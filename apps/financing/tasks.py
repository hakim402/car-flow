from celery import shared_task
from django.utils import timezone

from apps.communications import notification_engine
from apps.core.tenancy import company_scope

from .models import AgreementStatus, AgreementType, FinanceAgreement, InstallmentReminder
from .services import installment_summary


@shared_task
def send_financing_due_reminders() -> int:
    """Send selected due/overdue reminders once per installment per day."""
    today = timezone.localdate()
    sent = 0
    agreements = FinanceAgreement.all_objects.filter(
        status__in=[AgreementStatus.ACTIVE, AgreementStatus.DEFAULTED],
        agreement_type=AgreementType.DEALER_INSTALLMENT,
    ).select_related("company", "sale__customer")
    for agreement in agreements:
        with company_scope(agreement.company):
            for installment in agreement.installments.all():
                summary = installment_summary(installment, today)
                days_until = (installment.due_date - today).days
                kind = None
                if summary["outstanding"] <= 0:
                    continue
                if days_until == 3:
                    kind = "due_soon"
                elif days_until == 0:
                    kind = "due_today"
                elif summary["days_overdue"] in {1, 7, 14, 30, 60, 90}:
                    kind = "overdue"
                if kind is None:
                    continue
                _, created = InstallmentReminder.objects.get_or_create(
                    company=agreement.company,
                    installment=installment,
                    kind=kind,
                    reminder_date=today,
                )
                if not created:
                    continue
                sent += notification_engine.notify(
                    "installment_due",
                    company=agreement.company,
                    customer=agreement.sale.customer,
                    context={
                        "agreement": agreement.number,
                        "sequence": installment.sequence,
                        "amount": summary["outstanding"],
                        "currency": agreement.currency,
                        "due_date": installment.due_date.isoformat(),
                    },
                )
    return sent
