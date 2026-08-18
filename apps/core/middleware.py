"""TenantMiddleware (agent.md §5).

Sets the request-scoped tenant from the *authenticated user's company* —
never from client-supplied input — and clears it afterwards. Runs after
AuthenticationMiddleware; every tenant-aware app depends on it.
"""
from .tenancy import reset_current_company, set_current_company


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        company = getattr(user, "company", None) if user.is_authenticated else None
        token = set_current_company(company)
        try:
            return self.get_response(request)
        finally:
            reset_current_company(token)
