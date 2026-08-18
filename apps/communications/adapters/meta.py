"""Meta Graph API adapter — shared by WhatsApp, Messenger and Instagram
(agent.md §7.2): same Graph API, same webhook verification, same app
credentials; branching happens only on the payload's object type.

Only instantiated when `META_ENABLED` is True (see factory in base.py);
with the flag off this module is never reached at runtime.
"""
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from .base import BaseChannelAdapter, NormalizedInboundMessage, OutboundContent, SendResult

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v19.0"


class MetaAdapter(BaseChannelAdapter):
    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------
    def send(self, conversation, content: OutboundContent) -> SendResult:
        identity = conversation.channel.identities.filter(customer=conversation.customer).first()
        if identity is None:
            return SendResult(success=False, error="No external identity for customer on channel")
        endpoint_id = self._endpoint_id_for(conversation)
        if not endpoint_id:
            return SendResult(success=False, error="Channel credentials lack a send endpoint id")
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{endpoint_id}/messages"
        payload = {
            "messaging_product": self._messaging_product(),
            "to": identity.external_id,
            "type": "text",
            "text": {"body": content.text},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            body = exc.read().decode("utf-8", errors="replace")[:500]
            logger.error("Meta send failed (%s): %s", exc.code, body)
            return SendResult(success=False, error=f"HTTP {exc.code}")
        except urllib.error.URLError as exc:  # pragma: no cover - network
            logger.error("Meta send unreachable: %s", exc.reason)
            return SendResult(success=False, error=str(exc.reason))
        messages = data.get("messages") or []
        external_id = messages[0].get("id", "") if messages else ""
        return SendResult(success=True, external_message_id=external_id)

    # ------------------------------------------------------------------
    # Webhook verification (HMAC-SHA256 over the raw body, §7.3)
    # ------------------------------------------------------------------
    def verify_signature(self, request) -> bool:
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not signature.startswith("sha256=") or not settings.META_APP_SECRET:
            return False
        digest = hmac.new(
            settings.META_APP_SECRET.encode("utf-8"),
            request.body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(f"sha256={digest}", signature)

    # ------------------------------------------------------------------
    # Inbound parsing (normalized across WhatsApp/Messenger/Instagram)
    # ------------------------------------------------------------------
    def parse_payload(self, payload: dict) -> list[NormalizedInboundMessage]:
        results: list[NormalizedInboundMessage] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []) or []:
                    sender = message.get("from", "")
                    results.append(
                        NormalizedInboundMessage(
                            external_id=message.get("id", ""),
                            external_sender_id=sender,
                            # All Meta products key the 1:1 thread by sender id.
                            external_thread_id=sender,
                            body=(message.get("text") or {}).get("body", ""),
                            raw_payload=payload,
                        )
                    )
        return results

    # ------------------------------------------------------------------
    # Type-specific plumbing
    # ------------------------------------------------------------------
    def _messaging_product(self) -> str:
        return "whatsapp" if self.channel.type == "whatsapp" else self.channel.type

    def _endpoint_id_for(self, conversation) -> str:
        """Which Graph endpoint sends for this channel type."""
        credentials = self.channel.credentials or {}
        if self.channel.type == "whatsapp":
            return credentials.get("phone_number_id", settings.META_WHATSAPP_PHONE_NUMBER_ID)
        if self.channel.type == "messenger":
            return credentials.get("page_id", settings.META_MESSENGER_PAGE_ID)
        return credentials.get("page_id", settings.META_INSTAGRAM_PAGE_ID)
