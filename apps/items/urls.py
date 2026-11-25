from django.urls import path

from . import views

app_name = "items"

urlpatterns = [
    path("report/<str:kind>/", views.report, name="report"),
    path("<int:pk>/", views.item_detail, name="detail"),
    path("<int:pk>/withdraw/", views.withdraw, name="withdraw"),
    path("match/<int:pk>/dismiss/", views.dismiss_match, name="dismiss_match"),
]
