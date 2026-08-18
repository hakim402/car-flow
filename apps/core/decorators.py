"""View-level helpers shared by every business app."""
from functools import wraps

from django.core.exceptions import PermissionDenied


def require_permission(codename: str):
    """Deny the request unless the user's roles grant `codename` (§8).

    Tenant scoping is already enforced by TenantManager; this check adds the
    role dimension on top of it.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if not user.has_permission(codename):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
