from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.stock_list, name="list"),
    path("<int:pk>/status/", views.stock_update_status, name="update_status"),
]
