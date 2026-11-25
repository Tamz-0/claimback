from django.urls import path

from . import views

app_name = "claims"

urlpatterns = [
    path("item/<int:item_pk>/", views.claim_item, name="create"),
    path("<int:pk>/", views.claim_detail, name="detail"),
    path("<int:pk>/withdraw/", views.withdraw, name="withdraw"),
]
