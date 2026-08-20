from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(ModelAdmin):
    search_fields = ("name",)
