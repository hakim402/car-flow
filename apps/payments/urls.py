from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("", views.entry_list, name="list"),
    path("add/", views.payment_create, name="create"),
    path("<int:pk>/reverse/", views.entry_reverse, name="reverse"),
]
