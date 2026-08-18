"""Adapter layer (agent.md §7.2). Business apps never import from here —
they call `apps.communications.notification_engine.notify(...)`.

The factory at the bottom is the ONLY place that branches on `*_ENABLED`
settings (§12): every disabled channel silently degrades to NullChannelAdapter.
"""
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class OutboundContent:
    text: str
    media: list = field(default_factory=list)


@dataclass
class SendResult:
    success: bool
    external_message_id: str = ""
    error: str = ""


@dataclass
class NormalizedInboundMessage:
    external_id: str
    external_sender_id: str
    external_thread_id: str
    body: str
    raw_payload: dict


class BaseChannelAdapter(ABC):
    """Every provider implements exactly this interface (§7.2)."""

    def __init__(self, channel):
        self.channel = channel

    @abstractmethod
    def send(self, conversation, content: OutboundContent) -> SendResult:
        ...

    @abstractmethod
    def parse_payload(self, payload: dict) -> list[NormalizedInboundMessage]:
        ...

    @abstractmethod
    def verify_signature(self, request) -> bool:
        ...

    def parse_webhook(self, request) -> list[NormalizedInboundMessage]:
        """Default webhook entry: decode the body, defer to parse_payload."""
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("Unparseable webhook body on channel %s", self.channel.pk)
            return []
        return self.parse_payload(payload)


class NullChannelAdapter(BaseChannelAdapter):
    """Fallback for every disabled integration (§12.2): logs and no-ops.
    Inbound parsing yields nothing because disabled channels never receive
    signed webhooks; outbound reports success so callers can record the
    attempt as `skipped_disabled`."""

    def send(self, conversation, content: OutboundContent) -> SendResult:
        logger.info(
            "[integrations off] Would send on channel %s (%s): %.120s",
            self.channel.pk, self.channel.type, content.text,
        )
        return SendResult(success=True)

    def parse_payload(self, payload: dict) -> list[NormalizedInboundMessage]:
        return []

    def verify_signature(self, request) -> bool:
        return True


def get_channel_adapter(channel) -> BaseChannelAdapter:
    """Factory: the single place integration toggles are consulted (§12)."""
    from ..models import META_CHANNEL_TYPES
    from .meta import MetaAdapter

    if channel.type in META_CHANNEL_TYPES and settings.META_ENABLED:
        return MetaAdapter(channel)
    # Telegram/Email/SMS adapters arrive in Phase 2; everything disabled
    # or not-yet-built falls through to the Null adapter.
    return NullChannelAdapter(channel)
