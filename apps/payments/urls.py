from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("", views.entry_list, name="list"),
    path("accounts/", views.account_list, name="account_list"),
    path("accounts/add/", views.account_create, name="account_create"),
    path("add/", views.payment_create, name="create"),
    path("add/supplier/", views.supplier_payment_create, name="supplier_payment"),
    path("<int:pk>/receipt/", views.entry_receipt, name="receipt"),
    path("<int:pk>/reverse/", views.entry_reverse, name="reverse"),
]
