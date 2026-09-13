from django.urls import path

from . import workspace_views

app_name = "accounting"

urlpatterns = [
    path("reports/<slug:key>/", workspace_views.workspace, name="report"),
]
