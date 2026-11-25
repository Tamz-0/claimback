from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CampusUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Campus", {"fields": ("affiliation", "campus_id", "phone")}),)
    list_display = ("username", "email", "first_name", "last_name", "affiliation", "is_staff")
    list_filter = UserAdmin.list_filter + ("affiliation", "groups")
