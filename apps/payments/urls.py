from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("", views.entry_list, name="list"),
    path("add/", views.payment_create, name="create"),
    path("add/supplier/", views.supplier_payment_create, name="supplier_payment"),
    path("<int:pk>/reverse/", views.entry_reverse, name="reverse"),
]
