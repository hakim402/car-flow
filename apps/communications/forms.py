import json

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin

from .models import Channel, ChannelType


class ReplyForm(StyledFormMixin, forms.Form):
    body = forms.CharField(
        label=_("message"),
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": _("Type a message…")}),
    )


class ChannelForm(StyledFormMixin, forms.Form):
    type = forms.ChoiceField(label=_("type"), choices=ChannelType.choices)
    active = forms.BooleanField(label=_("active"), initial=True, required=False)
    credentials = forms.CharField(
        label=_("credentials (JSON)"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": '{"phone_number_id": "..."}'}),
    )

    def clean_credentials(self):
        raw = self.cleaned_data["credentials"].strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise forms.ValidationError(_("Credentials must be valid JSON.")) from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError(_("Credentials must be a JSON object."))
        return parsed


class ChannelUpdateForm(ChannelForm):
    """Same fields; the instance is applied by the view."""

    def __init__(self, *args, instance: Channel | None = None, **kwargs):
        self.instance = instance
        if instance is not None:
            kwargs.setdefault(
                "initial",
                {
                    "type": instance.type,
                    "active": instance.active,
                    "credentials": json.dumps(instance.credentials or {}),
                },
            )
        super().__init__(*args, **kwargs)
