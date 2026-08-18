"""Shared model primitives for append-only financial rows (agent.md §6)."""
from django.db import models
from django.utils.translation import gettext_lazy as _


class ImmutableRecordError(RuntimeError):
    """Raised when code tries to edit or delete an immutable financial row."""


class ImmutableModel(models.Model):
    """Rows are appended only — corrections are new rows referencing the
    original, never UPDATE/DELETE. Enforced at the model level."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise ImmutableRecordError(
                f"{type(self).__name__} rows are immutable; record a "
                "correction/reversal row instead of editing."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError(
            f"{type(self).__name__} rows cannot be deleted; record a "
            "correction/reversal row instead."
        )
