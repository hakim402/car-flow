"""Conversation Hub core models (agent.md §7.1, built exactly to spec).

This app is reusable infrastructure: it knows nothing about specific
providers except through the adapter layer, and business apps only ever
touch it via `notification_engine.notify(...)`.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CompanyConsistencyMixin
from apps.core.tenancy import TenantModel


class ChannelType(models.TextChoices):
    WHATSAPP = "whatsapp", _("WhatsApp")
    MESSENGER = "messenger", _("Messenger")
    INSTAGRAM = "instagram", _("Instagram")
    TELEGRAM = "telegram", _("Telegram")
    EMAIL = "email", _("Email")
    SMS = "sms", _("SMS")


# Channel families that share the Meta Graph API plumbing (§7.2).
META_CHANNEL_TYPES = (ChannelType.WHATSAPP, ChannelType.MESSENGER, ChannelType.INSTAGRAM)


class Channel(TenantModel):
    type = models.CharField(_("type"), max_length=20, choices=ChannelType.choices)
    credentials = models.JSONField(_("credentials"), default=dict, blank=True)
    active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("channel")
        verbose_name_plural = _("channels")
        ordering = ["type"]

    def __str__(self):
        return f"{self.get_type_display()} #{self.pk}"


class ConversationStatus(models.TextChoices):
    OPEN = "open", _("Open")
    CLOSED = "closed", _("Closed")


class Conversation(TenantModel, CompanyConsistencyMixin):
    company_relations = ("customer", "channel")

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="conversations",
        verbose_name=_("customer"),
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        related_name="conversations",
        verbose_name=_("channel"),
    )
    external_thread_id = models.CharField(_("external thread id"), max_length=255, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_conversations",
        verbose_name=_("assigned to"),
        null=True,
        blank=True,
    )
    status = models.CharField(
        _("status"), max_length=20, choices=ConversationStatus.choices, default=ConversationStatus.OPEN
    )
    last_message_at = models.DateTimeField(_("last message at"), null=True, blank=True)

    class Meta:
        verbose_name = _("conversation")
        verbose_name_plural = _("conversations")
        ordering = ["-last_message_at"]

    def __str__(self):
        return f"{self.customer} — {self.channel}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("communications:conversation_detail", kwargs={"pk": self.pk})


class MessageDirection(models.TextChoices):
    IN = "in", _("Inbound")
    OUT = "out", _("Outbound")


class MessageStatus(models.TextChoices):
    QUEUED = "queued", _("Queued")
    SENT = "sent", _("Sent")
    DELIVERED = "delivered", _("Delivered")
    READ = "read", _("Read")
    FAILED = "failed", _("Failed")
    # The channel's integration is switched off (§12): nothing was sent.
    SKIPPED_DISABLED = "skipped_disabled", _("Skipped (integration disabled)")


class Message(TenantModel):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name=_("conversation"),
    )
    direction = models.CharField(_("direction"), max_length=5, choices=MessageDirection.choices)
    body = models.TextField(_("body"))
    media = models.JSONField(_("media"), default=list, blank=True)
    external_message_id = models.CharField(_("external message id"), max_length=255, blank=True)
    status = models.CharField(
        _("status"), max_length=20, choices=MessageStatus.choices, default=MessageStatus.QUEUED
    )
    # Raw provider payload is stored BEFORE parsing (§7.3): provider schema
    # changes must never lose data, only require reprocessing.
    raw_payload = models.JSONField(_("raw payload"), null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("message")
        verbose_name_plural = _("messages")
        ordering = ["created_at"]
        constraints = [
            # Webhook redelivery must never create duplicate rows (§7.3).
            models.UniqueConstraint(
                fields=["company", "external_message_id"],
                condition=~models.Q(external_message_id=""),
                name="unique_external_message_per_company",
            )
        ]

    def __str__(self):
        return f"{self.get_direction_display()} — {self.body[:40]}"


class CustomerChannelIdentity(TenantModel, CompanyConsistencyMixin):
    """Maps one external provider id to exactly one customer (§7.4).
    Never merge distinct external ids silently."""

    company_relations = ("customer", "channel")

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="channel_identities",
        verbose_name=_("customer"),
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        related_name="identities",
        verbose_name=_("channel"),
    )
    external_id = models.CharField(_("external id"), max_length=255)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("customer channel identity")
        verbose_name_plural = _("customer channel identities")
        constraints = [
            models.UniqueConstraint(
                fields=["company", "channel", "external_id"],
                name="unique_external_id_per_channel",
            )
        ]

    def __str__(self):
        return f"{self.customer} @ {self.channel}"
