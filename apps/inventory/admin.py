"""Django Admin registrations (Super Admin only, README §8.1).

Tenant-scoped models are fail-closed by default; the admin runs without a
request tenant, so every queryset here is the explicit `all_objects` escape
hatch (§25.1). Movements are append-only history — read-only here.
"""
from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import InventoryLocation, InventoryMovement, VehicleStock


@admin.register(InventoryLocation)
class InventoryLocationAdmin(ModelAdmin):
    list_display = ("name", "branch", "company", "type", "code", "active")
    list_filter = ("active", "type")
    search_fields = ("name", "code")

    def get_queryset(self, request):
        return self.model.all_objects.all()


@admin.register(VehicleStock)
class VehicleStockAdmin(ModelAdmin):
    list_display = ("vehicle", "branch", "location", "status", "condition", "received_at")
    list_filter = ("status", "condition")
    search_fields = ("vehicle__vin", "vehicle__make", "vehicle__model")

    def get_queryset(self, request):
        return self.model.all_objects.all()


@admin.register(InventoryMovement)
class InventoryMovementAdmin(ModelAdmin):
    list_display = ("vehicle", "movement_type", "from_branch", "to_branch", "moved_at")
    list_filter = ("movement_type",)
    search_fields = ("vehicle__vin", "notes")
    readonly_fields = [field.name for field in InventoryMovement._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return self.model.all_objects.all()
