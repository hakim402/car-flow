from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="list"),
    path("add/", views.document_upload, name="upload"),
    # Upload box reached from a vehicle detail page (vehicle locked).
    path(
        "add/vehicle/<int:vehicle_pk>/",
        views.document_upload,
        name="upload_for_vehicle",
    ),
    # Upload box reached from a customer detail page (customer locked).
    path(
        "add/customer/<int:customer_pk>/",
        views.document_upload,
        name="upload_for_customer",
    ),
    # Upload box reached from a supplier detail page (supplier locked).
    path(
        "add/supplier/<int:supplier_pk>/",
        views.document_upload,
        name="upload_for_supplier",
    ),
    path(
        "add/financing/<int:agreement_pk>/",
        views.document_upload,
        name="upload_for_financing",
    ),
]
