from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import activate
from django.views.decorators.http import require_POST


@login_required
def dashboard(request):
    """Post-login landing screen; app tiles are added as each app ships."""
    return render(request, "accounts/dashboard.html")


@require_POST
def set_language(request):
    """Session-based language switcher (§11.2): stores the choice on both the
    session and the user's preferred_language, then reloads the same page.
    No locale-prefixed URLs — this is an internal system."""
    language = request.POST.get("language", "")
    if language in {code for code, _name in settings.LANGUAGES}:
        if hasattr(request, "session"):
            request.session["django_language"] = language
        else:
            activate(language)
        if request.user.is_authenticated:
            user = request.user
            if user.preferred_language != language:
                user.preferred_language = language
                user.save(update_fields=["preferred_language"])
    return redirect(request.META.get("HTTP_REFERER") or "/")
