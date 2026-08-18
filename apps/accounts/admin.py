"""Minimal Super Admin admin registrations (agent.md §8.1).

Operational/debugging tool only — no list_display polish, and no registration
for models that daily work happens on through the app's own UI.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Role, User


@admin.register(User)
class CarFlowUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "CarFlow",
            {"fields": ("company", "branch", "roles", "preferred_language")},
        ),
    )


admin.site.register(Role)
