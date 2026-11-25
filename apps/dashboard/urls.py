from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("me/", views.home, name="home"),
    path("desk/", views.desk, name="desk"),
    path("desk/item/<int:pk>/", views.desk_item, name="desk_item"),
    path("desk/claim/<int:pk>/", views.desk_claim, name="desk_claim"),
    path("desk/handover/<int:pk>/", views.desk_handover, name="desk_handover"),
    path("desk/matches/", views.desk_matches, name="desk_matches"),
    path("desk/matches/<int:pk>/", views.desk_match_action, name="desk_match_action"),
    path("desk/audit/", views.desk_audit, name="desk_audit"),
    path("reports/", views.reports, name="reports"),
]
