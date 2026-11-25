from django.contrib import admin

from .models import Claim


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "claimant", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = [f.name for f in Claim._meta.fields]  # change state only through the workflow

    def has_add_permission(self, request):
        return False
