"""Conversation Hub services: inbound processing (§7.3/§7.4) and outbound
replies. Everything persists raw payloads and dedupes on external ids."""
import logging

from apps.customers.models import Customer

from .adapters import NullChannelAdapter, OutboundContent, get_channel_adapter
from .models import (
    Conversation,
    CustomerChannelIdentity,
    Message,
    MessageDirection,
    MessageStatus,
)

logger = logging.getLogger(__name__)


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
