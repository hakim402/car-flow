"""Inbound webhook endpoints (§7.3). The view does ONLY:
verify → enqueue raw payload → return 200. Meta retries up to 7 days on
non-200, so this must stay fast and idempotent."""
import json

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .adapters.meta import MetaAdapter
from .tasks import process_meta_webhook


@csrf_exempt
@require_http_methods(["GET", "POST"])
def meta_webhook(request):
    if request.method == "GET":
        # Meta URL-verification handshake.
        if (
            request.GET.get("hub.mode") == "subscribe"
            and settings.META_ENABLED
            and request.GET.get("hub.verify_token") == settings.META_WEBHOOK_VERIFY_TOKEN
        ):
            return HttpResponse(request.GET.get("hub.challenge", ""))
        return HttpResponseForbidden()

    if not settings.META_ENABLED:
        # §12: disabled integrations refuse loudly but harmlessly.
        return HttpResponse(
            "META_ENABLED is off — webhook payloads are not accepted.",
            status=503,
            content_type="text/plain",
        )

    # Signature is verified against the shared app secret; no channel row
    # is needed for that, so the adapter is built without one.
    if not MetaAdapter(channel=None).verify_signature(request):
        return HttpResponseForbidden("Bad signature")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return HttpResponse("Unparseable payload", status=400)

    process_meta_webhook.delay(payload)
    return HttpResponse(status=200)
