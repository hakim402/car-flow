"""Shared form styling so every app's inputs match the Tailwind UI."""
from django import forms

INPUT_CLASS = (
    "w-full rounded-xl border border-slate-300 bg-slate-50 px-3.5 py-2.5 text-sm "
    "text-slate-800 shadow-sm outline-none transition placeholder:text-slate-400 "
    "focus:border-brand-500 focus:bg-white focus:ring-4 focus:ring-brand-100"
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
