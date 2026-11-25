from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("board", views.BoardViewSet, basename="board")
router.register("items", views.ItemViewSet, basename="items")
router.register("claims", views.ClaimViewSet, basename="claims")
router.register("handovers", views.HandoverViewSet, basename="handovers")

app_name = "api"
urlpatterns = router.urls
