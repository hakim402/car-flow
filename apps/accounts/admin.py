"""Minimal Super Admin admin registrations (agent.md §8.1).

Operational/debugging tool only — no list_display polish, and no registration
for models that daily work happens on through the app's own UI.
Styled by django-unfold (UNFOLD settings in config/settings/base.py).
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import Role, User


@admin.register(User)
class AmoxrunsUserAdmin(DjangoUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "AMOXRUNS",
            {"fields": ("company", "branch", "roles", "preferred_language")},
        ),
    )
    list_display = ("email", "username", "company", "is_staff")
    search_fields = ("email", "username", "first_name", "last_name")
    ordering = ("email",)


@admin.register(Role)
class RoleAdmin(ModelAdmin):
    list_display = ("name", "key", "system")
