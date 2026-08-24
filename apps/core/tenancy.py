"""Shared multi-tenancy infrastructure for AUTOMEX CarFlow (agent.md §5).

Every tenant-scoped model inherits from `TenantModel` and is queried through
`TenantManager`, which filters by the company set on the request by
`TenantMiddleware` — never by client-supplied input.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

from .models import CompanyConsistencyMixin

# Request-scoped tenant context, set by TenantMiddleware.
_current_company = ContextVar("carflow_current_company", default=None)


def set_current_company(company):
    """Set the tenant for the current request/thread. Returns a reset token."""
    return _current_company.set(company)


def reset_current_company(token):
    """Restore the previous tenant context using the token from set()."""
    _current_company.reset(token)


def get_current_company():
    """Return the Organization for the current request, or None."""
    return _current_company.get()


@contextmanager
def company_scope(company):
    """Temporarily scope tenant queries to `company` (used by management
    commands / Celery tasks that run outside a request cycle)."""
    token = set_current_company(company)
    try:
        yield
    finally:
        _current_company.reset(token)


class NoTenantContext(Exception):
    """Raised when a tenant-scoped query runs without tenant context."""


class TenantQuerySet(models.QuerySet):
    """Queryset that restricts every lookup to the current tenant."""

    def for_current_company(self):
        company = get_current_company()
        if company is None:
            raise NoTenantContext(
                "Tenant-scoped query on "
                f"{self.model.__name__} without tenant context. "
                "Requests go through TenantMiddleware; background work must "
                "use company_scope()."
            )
        return self.filter(company=company)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Fail-closed default manager (README §2.5, §25.1).

    `objects` filters by the current company and RAISES `NoTenantContext`
    when no tenant context exists — tenant-scoped access must never fail
    open. `all_objects` is the explicit, auditable escape hatch for trusted
    Super Admin/system operations (cross-tenant jobs, admin, audits).
    """

    def get_queryset(self):
        company = get_current_company()
        if company is None:
            raise NoTenantContext(
                "Tenant-scoped query on "
                f"{self.model.__name__} without tenant context. "
                "Requests go through TenantMiddleware; background work must "
                "use company_scope(); unrestricted system access must use "
                "all_objects explicitly."
            )
        return TenantQuerySet(self.model, using=self._db).filter(company=company)


class TenantModel(CompanyConsistencyMixin, models.Model):
    """Abstract base for every tenant-scoped model (§5).

    `CompanyConsistencyMixin` is the FIRST base so its `clean()` resolves
    before Django's no-op `Model.clean()` (§25.2) — the mixin listed again
    on concrete models is documentation, not the mechanism."""

    company = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="company",
    )

    objects = TenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
