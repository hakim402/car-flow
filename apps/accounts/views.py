from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

# Session key LocaleMiddleware used before Django switched the canonical
# storage to the LANGUAGE_COOKIE; we still set it for backwards compatibility.
LANGUAGE_SESSION_KEY = "django_language"


def _language_cookie_response(response, language: str):
    """Persist the language choice where Django 5's LocaleMiddleware actually
    reads it: the `django_language` COOKIE (session alone is ignored)."""
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language,
        max_age=60 * 60 * 24 * 365,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )
    return response


class CarFlowLoginView(auth_views.LoginView):
    """Login by email (USERNAME_FIELD) that also activates the user's stored
    preferred_language (§11.2) immediately after authentication."""

    template_name = "accounts/login.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        language = getattr(self.request.user, "preferred_language", "") or ""
        if language in {code for code, _name in settings.LANGUAGES}:
            if hasattr(self.request, "session"):
                self.request.session[LANGUAGE_SESSION_KEY] = language
            response = _language_cookie_response(response, language)
        return response


@login_required
def dashboard(request):
    """Post-login landing screen; app tiles are added as each app ships."""
    return render(request, "accounts/dashboard.html")


@require_POST
def set_language(request):
    """Language switcher (§11.2): stores the choice in the language cookie
    (what LocaleMiddleware reads), the session, and the user's
    preferred_language, then reloads the same page."""
    language = request.POST.get("language", "")
    response = redirect(request.META.get("HTTP_REFERER") or "/")
    if language in {code for code, _name in settings.LANGUAGES}:
        response = _language_cookie_response(response, language)
        if hasattr(request, "session"):
            request.session[LANGUAGE_SESSION_KEY] = language
        if request.user.is_authenticated:
            user = request.user
            if user.preferred_language != language:
                user.preferred_language = language
                user.save(update_fields=["preferred_language"])
    return response
