from django.conf import settings


class AdminContentSecurityPolicyMiddleware:
    """Allow Unfold/Alpine interactivity only on the secure admin route."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        admin_prefix = f"/{settings.SUPERADMIN_URL.strip('/')}/"
        if request.path.startswith(admin_prefix):
            response["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            )
        return response
