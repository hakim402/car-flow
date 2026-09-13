"""Complete emergency registrations for the Unfold superadmin console."""

from django.contrib import admin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin

from apps.core.models import ImmutableModel
from apps.core.tenancy import TenantModel


class EmergencyModelAdmin(ModelAdmin):
    list_per_page = 50

    def get_queryset(self, request):
        if issubclass(self.model, TenantModel):
            return self.model.all_objects.all()
        return super().get_queryset(request)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        related_model = db_field.remote_field.model
        if isinstance(related_model, type) and issubclass(related_model, TenantModel):
            kwargs["queryset"] = related_model.all_objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        related_model = db_field.remote_field.model
        if isinstance(related_model, type) and issubclass(related_model, TenantModel):
            kwargs["queryset"] = related_model.all_objects.all()
        return super().formfield_for_manytomany(db_field, request, **kwargs)


def _register(model, *, readonly=False):
    if admin.site.is_registered(model):
        return
    fields = list(model._meta.fields)
    attrs = {
        "list_display": tuple(field.name for field in fields[:5]) or ("id",),
        "search_fields": tuple(
            field.name for field in fields
            if getattr(field, "get_internal_type", lambda: "")() in {"CharField", "TextField", "EmailField"}
        ),
        "list_filter": tuple(field.name for field in fields if getattr(field, "choices", None)),
    }
    if readonly or issubclass(model, ImmutableModel):
        attrs["readonly_fields"] = tuple(field.name for field in fields)
        attrs["has_add_permission"] = lambda self, request: False
        attrs["has_change_permission"] = lambda self, request, obj=None: False
        attrs["has_delete_permission"] = lambda self, request, obj=None: False
    admin.site.register(model, type(f"{model.__name__}EmergencyAdmin", (EmergencyModelAdmin,), attrs))


from apps.accounting.models import ReportExport, ReportShare, ReportShareAccess
from apps.accounts.models import Permission
from apps.communications.models import Channel, Conversation, CustomerChannelIdentity, Message, Notification, NotificationDeliveryLog, NotificationEvent, NotificationPreference
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.expenses.models import ExpenseCategory
from apps.financing.models import AgreementEvent, AgreementGuarantor, FinanceAgreement, FinancingPartner, Installment, InstallmentReminder, LenderDisbursement, PaymentAllocation
from apps.inventory.models import InventoryLocation, InventoryMovement, VehicleStock
from apps.payments.models import FinancialAccount, LedgerEntry, LedgerSequence
from apps.purchases.models import PurchaseOrder, PurchaseOrderLine, VehicleCostLine
from apps.sales.models import Invoice, Lead, Quotation, Reservation, Sale
from apps.suppliers.models import Supplier
from apps.vehicles.models import Vehicle


# Replace Django's stock Group admin with an Unfold-styled emergency form.
if admin.site.is_registered(Group):
    admin.site.unregister(Group)

_readonly = {InventoryMovement, LedgerEntry, VehicleCostLine, Installment, PaymentAllocation, LenderDisbursement, AgreementEvent, InstallmentReminder, NotificationDeliveryLog}
for _model in (
    Permission, Group, Vehicle, InventoryLocation, VehicleStock, InventoryMovement,
    Supplier, PurchaseOrder, PurchaseOrderLine, VehicleCostLine, Customer, Lead,
    Quotation, Reservation, Sale, Invoice, FinancialAccount, LedgerSequence,
    LedgerEntry, FinancingPartner, FinanceAgreement, Installment, PaymentAllocation,
    LenderDisbursement, AgreementGuarantor, AgreementEvent, InstallmentReminder,
    ExpenseCategory, ReportExport, ReportShare, ReportShareAccess, Channel,
    Conversation, Message, NotificationEvent, Notification, NotificationPreference,
    NotificationDeliveryLog, CustomerChannelIdentity, Document,
):
    _register(_model, readonly=_model in _readonly)
