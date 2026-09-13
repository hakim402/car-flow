"""Report permissions, shared by the workspace and delivery endpoints."""

from .reporting import REPORTS


def _explicit_permission(user, codename):
    # Exporting/sharing sensitive data must not inherit the legacy no-role fallback.
    return bool(
        user.is_superuser
        or user.is_super_admin
        or user.roles.filter(permissions__codename=codename).exists()
    )


def can_view_report(user, key):
    if (
        not user.is_authenticated
        or not user.is_active
        or not user.company_id
        or key not in REPORTS
    ):
        return False
    report = REPORTS[key]
    permissions = [report["permission"], *report.get("required_permissions", [])]
    return all(
        _explicit_permission(user, permission)
        if permission.startswith("reports.")
        else user.has_permission(permission)
        for permission in permissions
    )


def can_deliver_report(user, key, action="export"):
    return (
        action in {"export", "share"}
        and can_view_report(user, key)
        and _explicit_permission(user, f"reports.{action}")
    )
