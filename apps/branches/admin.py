from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Branch


@admin.register(Branch)
class BranchAdmin(ModelAdmin):
    list_display = ("name", "company")
    search_fields = ("name",)
