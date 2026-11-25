from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.notifications, name="notifications"),
    path("<int:pk>/", views.open_notification, name="open"),
]
