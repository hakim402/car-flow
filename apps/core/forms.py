"""Shared form styling so every app's inputs match the Tailwind UI."""
from django import forms

INPUT_CLASS = (
    "w-full rounded border border-slate-300 px-3 py-2 text-sm "
    "focus:border-amber-500 focus:outline-none"
)


class StyledFormMixin:
    """Applies Tailwind classes to every widget; mix in before forms.ModelForm."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect, forms.HiddenInput)):
                continue
            widget.attrs["class"] = " ".join(
                part for part in (widget.attrs.get("class", ""), INPUT_CLASS) if part
            )
