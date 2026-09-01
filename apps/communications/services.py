"""Conversation Hub services: inbound processing (§7.3/§7.4) and outbound
replies. Everything persists raw payloads and dedupes on external ids."""
import logging
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.customers.models import Customer

from .adapters import NullChannelAdapter, OutboundContent, get_channel_adapter
from .models import (
    Conversation,
    CustomerChannelIdentity,
    Message,
    MessageDirection,
    MessageStatus,
    Notification,
    NotificationEvent,
    NotificationPreference,
    NotificationStatus,
)

logger = logging.getLogger(__name__)

INTERNAL_EVENT_TEMPLATES = {
    "new_vehicle_added": "New vehicle added: {vehicle}.",
    "vehicle_sold": "Vehicle sold: {vehicle}.",
    "payment_received": "Payment received: {amount} {currency}.",
    "reservation_expiring": "Reservation expiring for: {vehicle}.",
    "lead_converted": "Lead converted: {customer}.",
    "purchase_order_received": "Purchase order received for {supplier}.",
    "supplier_payment_due": "Supplier payment due for {supplier}.",
}


def _event_template(event_key: str, context: dict | None = None) -> str:
    template = INTERNAL_EVENT_TEMPLATES.get(event_key, "New business event: {event}.")
    context = context or {}
    try:
        return template.format(**context, event=event_key)
    except KeyError:
        return template


def get_internal_recipients(company, roles=None, users=None):
    """Return user records targeted by a role-based internal alert."""
    if users is not None:
        return list(users)
    if not roles:
        return []
    role_qs = Role.objects.filter(key__in=roles)
    return list(company.users.filter(roles__in=role_qs).distinct())


def _channel_available(channel: str) -> bool:
    toggles = {
        "email": getattr(settings, "EMAIL_ENABLED", False),
        "sms": getattr(settings, "SMS_ENABLED", False),
        "whatsapp": getattr(settings, "META_ENABLED", False),
        "in_app": True,
    }
    return toggles.get(channel, False)


@transaction.atomic
def notify_internal_users(
    *,
    company,
    event_key: str,
    context: dict | None = None,
    roles=None,
    users=None,
    channel: str = "in_app",
):
    """Create internal notifications for users in the same company.

    The function is intentionally provider-agnostic: providers are configured in
    .env and validated by Django system checks. If a channel is disabled, the
    notification is still recorded in the database with a skipped status.
    """
    if users is None:
        recipients = get_internal_recipients(company, roles=roles or [], users=None)
    else:
        recipients = list(users)

    event, _ = NotificationEvent.objects.get_or_create(
        key=event_key,
        defaults={
            "label": event_key.replace("_", " ").title(),
            "default_template": INTERNAL_EVENT_TEMPLATES.get(event_key, "Business update."),
        },
    )

    created = []
    for user in recipients:
        if user.company_id != company.pk:
            continue
        title = event.label or event_key.replace("_", " ").title()
        message = _event_template(event_key, context)

        pref, _ = NotificationPreference.objects.get_or_create(
            company=company,
            user=user,
            event=event,
            defaults={"enabled": True, "email": True, "sms": False, "whatsapp": False, "in_app": True},
        )
        if not pref.enabled:
            continue

        status = NotificationStatus.SENT if channel == "in_app" else NotificationStatus.QUEUED
        if not _channel_available(channel):
            status = NotificationStatus.SKIPPED_DISABLED

        notification = Notification.objects.create(
            company=company,
            recipient=user,
            event=event,
            title=title,
            message=message,
            channel=channel,
            status=status,
            metadata={"event_key": event_key, "context": context or {}},
        )

        if not _channel_available(channel):
            notification.sent_at = timezone.now()
            notification.save(update_fields=["status", "sent_at"])
        created.append(notification)

    return created


def resolve_customer(channel, external_sender_id: str):
    """§7.4: known identity → existing customer; unknown → NEW customer +
    identity row. Distinct external ids are never merged silently."""
    identity = CustomerChannelIdentity.objects.filter(
        channel=channel, external_id=external_sender_id
    ).first()
    if identity is not None:
        return identity.customer
    customer = Customer.objects.create(
        company=channel.company,
        full_name=f"{channel.get_type_display()} {external_sender_id[-6:]}",
    )
    CustomerChannelIdentity.objects.create(
        company=channel.company,
        customer=customer,
        channel=channel,
        external_id=external_sender_id,
    )
    logger.info(
        "New customer %s created from %s sender %s",
        customer.pk, channel.type, external_sender_id,
    )
    return customer


def process_inbound_payload(channel, payload: dict) -> int:
    """Parse one raw webhook payload for a channel and persist messages.
    Returns the number of new messages stored (duplicates are skipped)."""
    adapter = get_channel_adapter(channel)
    stored = 0
    for inbound in adapter.parse_payload(payload):
        # Redelivery must not duplicate rows (§7.3) — check before anything.
        if inbound.external_id and Message.objects.filter(
            company=channel.company, external_message_id=inbound.external_id
        ).exists():
            continue
        customer = resolve_customer(channel, inbound.external_sender_id)
        conversation, _ = Conversation.objects.get_or_create(
            company=channel.company,
            channel=channel,
            customer=customer,
            external_thread_id=inbound.external_thread_id,
        )
        message = Message.objects.create(
            company=channel.company,
            conversation=conversation,
            direction=MessageDirection.IN,
            body=inbound.body,
            external_message_id=inbound.external_id,
            status=MessageStatus.DELIVERED,
            raw_payload=inbound.raw_payload,
        )
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=["last_message_at"])
        stored += 1
    return stored


def send_reply(conversation, text: str) -> Message:
    """Send an outbound message through the channel's adapter and persist the
    attempt — including the no-op case when the integration is off (§12)."""
    adapter = get_channel_adapter(conversation.channel)
    result = adapter.send(conversation, OutboundContent(text=text))
    if isinstance(adapter, NullChannelAdapter):
        status = MessageStatus.SKIPPED_DISABLED
    else:
        status = MessageStatus.SENT if result.success else MessageStatus.FAILED
    message = Message.objects.create(
        company=conversation.company,
        conversation=conversation,
        direction=MessageDirection.OUT,
        body=text,
        external_message_id=result.external_message_id,
        status=status,
    )
    conversation.last_message_at = message.created_at
    conversation.save(update_fields=["last_message_at"])
    return message
