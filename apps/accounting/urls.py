from django.urls import path

from . import views

app_name = "accounting"

urlpatterns = [
    path("", views.summary, name="summary"),
    path("receivables/", views.receivables, name="receivables"),
]
