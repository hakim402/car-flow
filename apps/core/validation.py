"""Reusable same-company relationship validation (README §25.2).

Cross-tenant relationships are the highest-risk integrity class: services,
models and forms all route through this single helper so the rule is defined
exactly once.
"""
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_same_company(company, relations: dict) -> None:
    """Raise `ValidationError` when a related tenant object belongs to a
    different company.

    `relations` maps a human-readable label to a related instance; `None`
    values (optional FKs) are skipped, and objects without a `company_id`
    attribute are ignored. `company` may be an instance or a pk.
    """
    company_id = getattr(company, "pk", company)
    if company_id is None:
        return
    offenders = []
    for label, obj in relations.items():
        if obj is None:
            continue
        obj_company_id = getattr(obj, "company_id", None)
        if obj_company_id is not None and obj_company_id != company_id:
            offenders.append(label)
    if offenders:
        raise ValidationError(
            _("These related objects belong to a different company: %(labels)s"),
            params={"labels": ", ".join(offenders)},
        )
