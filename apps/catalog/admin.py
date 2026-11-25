from django.contrib import admin

from .models import Category, Location


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "icon", "retention_days", "is_active")
    list_editable = ("retention_days", "is_active")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("full_name", "kind", "is_custody_point", "is_active")
    list_filter = ("kind", "is_custody_point", "is_active")
    search_fields = ("name",)
    autocomplete_fields = ("parent",)
