from django.contrib import admin

from .models import CustodyRecord, DisposalRecord, Handover


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CustodyRecord)
class CustodyRecordAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "item", "action", "location", "actor", "hash")
    list_filter = ("action",)


@admin.register(Handover)
class HandoverAdmin(ReadOnlyAdmin):
    list_display = ("item", "status", "scheduled_for", "method", "supervised_by", "completed_at")
    exclude = ("otp_hash",)


@admin.register(DisposalRecord)
class DisposalRecordAdmin(ReadOnlyAdmin):
    list_display = ("item", "method", "recipient", "approved_by", "created_at")
