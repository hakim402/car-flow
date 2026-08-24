"""Celery tasks for webhook processing (§7.3): the HTTP view only verifies
and enqueues; all parsing and side effects happen here."""
from celery import shared_task

from apps.core.tenancy import company_scope

from .models import META_CHANNEL_TYPES, Channel
from .services import process_inbound_payload


@shared_task
def process_meta_webhook(payload: dict) -> int:
    """Process one raw Meta webhook payload against every active Meta-family
    channel. Idempotent: message rows dedupe on `external_message_id`."""
    total = 0
    channels = Channel.all_objects.filter(type__in=META_CHANNEL_TYPES, active=True)
    for channel in channels:
        # Celery runs outside the request cycle: the tenant-scoped queries
        # inside process_inbound_payload need explicit context (§25.1).
        with company_scope(channel.company):
            total += process_inbound_payload(channel, payload)
    return total
