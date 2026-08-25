from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.stock_list, name="list"),
    path("<int:pk>/", views.stock_detail, name="stock_detail"),
    path("<int:pk>/status/", views.stock_update_status, name="update_status"),
    path("<int:pk>/move/", views.stock_move, name="move"),
    path("<int:pk>/transfer/", views.stock_transfer, name="transfer"),
    path("locations/", views.location_list, name="location_list"),
    path("locations/add/", views.location_create, name="location_create"),
    path("locations/<int:pk>/toggle/", views.location_toggle, name="location_toggle"),
]
