from django.urls import path

from . import views

app_name = "expenses"

urlpatterns = [
    path("", views.expense_list, name="list"),
    path("<int:pk>/", views.expense_detail, name="detail"),
    path("categories/", views.category_list, name="category_list"),
    path("categories/add/", views.category_create, name="category_create"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("add/", views.expense_create, name="create"),
    path("<int:pk>/reverse/", views.expense_reverse, name="reverse"),
]
