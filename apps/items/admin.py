from django.contrib import admin

from .models import Item, ItemPhoto


class PhotoInline(admin.TabularInline):
    model = ItemPhoto
    extra = 0
    readonly_fields = ("image", "thumbnail")


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "title", "category", "location", "status", "occurred_at", "reporter")
    list_filter = ("kind", "status", "category")
    search_fields = ("title", "description")
    inlines = [PhotoInline]
    # Private details are deliberately NOT editable in the admin: they live in the vault.
