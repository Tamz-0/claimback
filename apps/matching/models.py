from django.db import models

from apps.items.models import Item


class MatchSuggestion(models.Model):
    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        CONFIRMED = "confirmed", "Confirmed by owner/security"
        DISMISSED = "dismissed", "Dismissed"

    lost = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="matches_as_lost")
    found = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="matches_as_found")
    score = models.FloatField(db_index=True)
    breakdown = models.JSONField(default=dict)  # {"category": .., "attributes": .., "text": .., "location": .., "time": ..}
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUGGESTED)
    notified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-score"]
        unique_together = [("lost", "found")]

    def __str__(self):
        return f"{self.lost_id} ↔ {self.found_id} ({self.score:.2f})"
