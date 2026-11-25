from django.urls import path

from . import views

app_name = "board"

urlpatterns = [
    path("", views.board_list, name="list"),
    path("item/<int:pk>/", views.board_detail, name="detail"),
]
