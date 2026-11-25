from django.contrib import admin

from .models import MatchSuggestion


@admin.register(MatchSuggestion)
class MatchSuggestionAdmin(admin.ModelAdmin):
    list_display = ("lost", "found", "score", "status", "created_at")
    list_filter = ("status",)
