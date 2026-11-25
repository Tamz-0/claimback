from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
