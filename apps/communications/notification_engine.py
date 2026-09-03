"""The ONLY entry point business apps use to message customers (§7.2):

    notification_engine.notify(event="payment_recorded", company=..., customer=..., context={...})

The engine resolves the customer's channel identities and dispatches through
the Conversation Hub; adding channels never touches business code.
"""
import logging

from django.utils.translation import gettext

from apps.core.tenancy import company_scope

from .models import CustomerChannelIdentity
from .services import send_reply

logger = logging.getLogger(__name__)

# event → template with {placeholders} filled from `context`.
EVENT_TEMPLATES = {
    "payment_recorded": "Payment of {amount} {currency} was recorded on your account. Thank you!",
    "sale_completed": "Your purchase of {vehicle} is complete. Thank you for choosing AUTOMEX!",
    "installment_due": (
        "Installment {sequence} for agreement {agreement} has {amount} {currency} "
        "outstanding and is due on {due_date}."
    ),
}


def notify(event: str, company, customer, context: dict | None = None) -> int:
    """Dispatch `event` to the customer on every active channel identity.
    Returns the number of outbound messages attempted."""
    template = EVENT_TEMPLATES.get(event)
    if template is None:
        logger.warning("Unknown notification event: %s", event)
        return 0
    if customer is None:
        return 0
    try:
        text = gettext(template).format(**(context or {}))
    except KeyError:
        logger.exception("Missing context for event %s", event)
        return 0

    from .models import Conversation  # local import: avoid app-loading cycles

    sent = 0
    # `notify` may run from services, signals or Celery tasks: scope the
    # tenant-scoped queries explicitly so it works without a request (§25.1).
    with company_scope(company):
        identities = CustomerChannelIdentity.objects.filter(
            company=company, customer=customer, channel__active=True
        ).select_related("channel")
        for identity in identities:
            conversation, _ = Conversation.objects.get_or_create(
                company=company,
                channel=identity.channel,
                customer=customer,
                external_thread_id=identity.external_id,
            )
            send_reply(conversation, text)
            sent += 1
    if sent == 0:
        logger.info("notify(%s): no channel identities for customer %s", event, customer.pk)
    return sent
