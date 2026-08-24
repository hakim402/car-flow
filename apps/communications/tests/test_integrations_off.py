"""Integrations-off boot gate (agent.md §12, §10 Step 12).

The whole suite runs under `config.settings.test`, where every `*_ENABLED`
flag is False and every credential is empty. These tests pin that contract
and prove the Null adapter degrades gracefully end-to-end:
factory → send_reply → notification_engine → webhook endpoint.
"""
import pytest
from django.conf import settings
from django.test import Client

from apps.communications import notification_engine
from apps.communications.adapters import NullChannelAdapter, get_channel_adapter
from apps.communications.models import (
    Conversation,
    CustomerChannelIdentity,
    MessageDirection,
    MessageStatus,
)
from apps.communications.services import process_inbound_payload, send_reply
from apps.core.tenancy import company_scope
from apps.core.testing import ChannelFactory, CustomerFactory

TOGGLES = (
    "META_ENABLED",
    "TELEGRAM_ENABLED",
    "SMS_ENABLED",
    "EMAIL_ENABLED",
    "S3_ENABLED",
)
CREDENTIALS = (
    "META_APP_ID",
    "META_APP_SECRET",
    "META_ACCESS_TOKEN",
    "META_WEBHOOK_VERIFY_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "SMS_GATEWAY_URL",
    "SMS_GATEWAY_API_KEY",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
)


def test_every_toggle_off_and_credentials_empty():
    for flag in TOGGLES:
        assert getattr(settings, flag) is False, flag
    for credential in CREDENTIALS:
        assert getattr(settings, credential) == "", credential


@pytest.mark.django_db
def test_factory_returns_null_adapter_when_disabled():
    channel = ChannelFactory(type="whatsapp")
    assert isinstance(get_channel_adapter(channel), NullChannelAdapter)


@pytest.mark.django_db
def test_send_reply_persists_skipped_disabled():
    customer = CustomerFactory()
    channel = ChannelFactory(company=customer.company, type="whatsapp")
    with company_scope(customer.company):
        conversation = Conversation.objects.create(
            company=customer.company, customer=customer, channel=channel
        )

        message = send_reply(conversation, "Hello from CarFlow")
    assert message.status == MessageStatus.SKIPPED_DISABLED
    assert message.direction == MessageDirection.OUT
    assert message.body == "Hello from CarFlow"


@pytest.mark.django_db
def test_notify_runs_through_null_adapter():
    customer = CustomerFactory()
    channel = ChannelFactory(company=customer.company, type="whatsapp")
    with company_scope(customer.company):
        CustomerChannelIdentity.objects.create(
            company=customer.company,
            customer=customer,
            channel=channel,
            external_id="waid:93700000001",
        )

        sent = notification_engine.notify(
            "payment_recorded",
            company=customer.company,
            customer=customer,
            context={"amount": "5,000", "currency": "USD"},
        )
        assert sent == 1
        message = Conversation.objects.get(customer=customer).messages.get()
    assert message.status == MessageStatus.SKIPPED_DISABLED
    assert "5,000 USD" in message.body


@pytest.mark.django_db
def test_inbound_parsing_is_a_noop_when_disabled():
    channel = ChannelFactory(type="whatsapp")
    with company_scope(channel.company):
        stored = process_inbound_payload(channel, {"object": "whatsapp_business_account"})
    assert stored == 0


@pytest.mark.django_db
def test_meta_webhook_refuses_when_disabled():
    client = Client()
    post = client.post(
        "/webhooks/meta/", data="{}", content_type="application/json"
    )
    assert post.status_code == 503

    handshake = client.get(
        "/webhooks/meta/",
        {"hub.mode": "subscribe", "hub.verify_token": "whatever", "hub.challenge": "42"},
    )
    assert handshake.status_code == 403
