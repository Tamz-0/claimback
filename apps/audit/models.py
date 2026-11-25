from django.conf import settings
from django.db import models


class AuditEntry(models.Model):
    """Append-only log of every significant action in the system."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60, db_index=True)
    target_type = models.CharField(max_length=40)
    target_id = models.CharField(max_length=40)
    # Never put private-detail values in here; only ids and non-sensitive facts.
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "audit entries"

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.target_type}#{self.target_id}"


class Notification(models.Model):
    class Kind(models.TextChoices):
        MATCH_FOUND = "match_found", "Possible match found"
        CLAIM_SUBMITTED = "claim_submitted", "Claim submitted on your found item"
        VERIFICATION_REQUIRED = "verification_required", "Verification required"
        CLAIM_DECIDED = "claim_decided", "Claim decision"
        HANDOVER_SCHEDULED = "handover_scheduled", "Handover scheduled"
        HANDOVER_DONE = "handover_done", "Item handed over"
        AGEING_WARNING = "ageing_warning", "Unclaimed item ageing warning"
        GENERAL = "general", "General"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30, choices=Kind.choices, default=Kind.GENERAL)
    message = models.CharField(max_length=300)
    url = models.CharField(max_length=300, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user}: {self.message}"
