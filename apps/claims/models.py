from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.items.models import Item


class Claim(models.Model):
    """
    Someone says a found item is theirs.

    Lifecycle:
        verifying  -> claimant answers the challenge
        verified   -> challenge passed, waiting for security approval
        review     -> borderline score, security compares answers
        approved   -> security approved; handover can be scheduled
        handed_over-> item returned (terminal)
        rejected / withdrawn (terminal)

    Several claims may exist on one item at once (competing claims). Only one
    can ever be approved; approving it auto-rejects the others.
    """

    class Status(models.TextChoices):
        VERIFYING = "verifying", "Verification required"
        REVIEW = "review", "Under security review"
        VERIFIED = "verified", "Verified – awaiting approval"
        APPROVED = "approved", "Approved – awaiting handover"
        HANDED_OVER = "handed_over", "Handed over"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    OPEN_STATES = {Status.VERIFYING, Status.REVIEW, Status.VERIFIED, Status.APPROVED}

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="claims")
    claimant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="claims")
    lost_report = models.ForeignKey(
        Item, null=True, blank=True, on_delete=models.SET_NULL, related_name="claims_as_lost_report",
        help_text="The claimant's own lost report, if they filed one",
    )
    statement = models.TextField(blank=True, help_text="Where/when you lost it, anything else useful")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.VERIFYING, db_index=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Database-level guarantee: at most one approved/handed-over claim per item.
            models.UniqueConstraint(
                fields=["item"], condition=models.Q(status__in=["approved", "handed_over"]),
                name="one_winning_claim_per_item",
            ),
        ]

    def __str__(self):
        return f"Claim #{self.pk} on {self.item} by {self.claimant}"

    def get_absolute_url(self):
        return reverse("claims:detail", args=[self.pk])

    @property
    def is_open(self):
        return self.status in self.OPEN_STATES

    @property
    def verification_passed(self):
        ch = getattr(self, "challenge", None)
        return ch is not None and ch.status == ch.Status.PASSED
