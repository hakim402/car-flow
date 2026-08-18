from django.urls import path

from . import views

app_name = "communications"

urlpatterns = [
    path("", views.conversation_list, name="conversation_list"),
    path("<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("<int:pk>/reply/", views.conversation_reply, name="conversation_reply"),
    path("channels/", views.channel_list, name="channel_list"),
    path("channels/add/", views.channel_create, name="channel_create"),
    path("channels/<int:pk>/edit/", views.channel_edit, name="channel_edit"),
]
