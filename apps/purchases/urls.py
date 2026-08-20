from django.urls import path

from . import views

app_name = "purchases"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("add/", views.order_create, name="create"),
    path("<int:pk>/", views.order_detail, name="detail"),
    path("<int:pk>/lines/add/", views.order_add_line, name="add_line"),
    path("<int:pk>/advance/", views.order_advance, name="advance"),
    path("<int:pk>/receive/", views.order_receive, name="receive"),
]
