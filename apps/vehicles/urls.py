from django.urls import path

from . import views

app_name = "vehicles"

urlpatterns = [
    path("", views.vehicle_list, name="list"),
    path("add/", views.vehicle_create, name="create"),
    path("<int:pk>/", views.vehicle_detail, name="detail"),
    path("<int:pk>/edit/", views.vehicle_edit, name="edit"),
    path("<int:pk>/costs/add/", views.vehicle_add_cost, name="add_cost"),
]
