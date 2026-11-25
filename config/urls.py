from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

admin.site.site_header = "Campus Lost & Found – Administration"
admin.site.site_title = "Lost & Found admin"

urlpatterns = [
    path("", include("apps.board.urls")),
    path("items/", include("apps.items.urls")),
    path("claims/", include("apps.claims.urls")),
    path("notifications/", include("apps.audit.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("api/", include("apps.api.urls")),
    path("", include("apps.dashboard.urls")),
    path("admin/", admin.site.urls),
]

if settings.SERVE_MEDIA and not settings.USE_SUPABASE_STORAGE:
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]
