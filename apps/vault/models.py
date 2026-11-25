"""
The vault: private identifying details and verification challenges.

Structural protections (so private data cannot leak by accident):

1. PrivateDetail -> Item uses related_name="+": there is NO `item.private_details`.
   Code that only has an Item (serializers, templates, the public board) has
   no path to these rows.
2. The default manager `PrivateDetail.objects` returns an EMPTY queryset.
   The only way to read rows is `PrivateDetail.vault`, which is used solely
   inside apps/vault/services.py.
3. Question and answer are encrypted at rest (EncryptedTextField).
4. A test (tests/test_structure.py) fails the build if any public module
   imports apps.vault.
"""

from django.conf import settings
from django.db import models

from apps.items.models import Item

from .crypto import EncryptedTextField


class LockedManager(models.Manager):
    """Default manager: deliberately returns nothing."""

    def get_queryset(self):
        return super().get_queryset().none()


class VaultManager(models.Manager):
    """Real manager. Use only from apps.vault.services."""


class PrivateDetail(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="+")
    question = EncryptedTextField(help_text="e.g. 'What sticker is on the back?'")
    answer = EncryptedTextField(help_text="e.g. 'NASA logo'")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LockedManager()
    vault = VaultManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "vault"   # Django internals (cascade delete) still work

    def __str__(self):
        return f"Private detail #{self.pk} for item #{self.item_id}"


class VerificationChallenge(models.Model):
    """The challenge a claimant must answer. One per claim."""

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting answers"
        PASSED = "passed", "Passed"
        REVIEW = "review", "Needs security review"
        FAILED = "failed", "Failed – can retry"
        LOCKED = "locked", "Failed – no attempts left"
        REJECTED = "rejected", "Rejected by security"

    claim = models.OneToOneField("claims.Claim", on_delete=models.CASCADE, related_name="challenge")
    # Ids of PrivateDetail rows selected for this challenge (not the content).
    detail_ids = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=2)
    best_score = models.FloatField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def attempts_left(self):
        return max(0, self.max_attempts - self.attempts)

    @property
    def can_answer(self):
        return self.status in (self.Status.PENDING, self.Status.FAILED) and self.attempts_left > 0

    def __str__(self):
        return f"Challenge for claim #{self.claim_id} ({self.status})"


class VerificationAttempt(models.Model):
    """A claimant's answers. Encrypted; visible only to security reviewers."""

    challenge = models.ForeignKey(VerificationChallenge, on_delete=models.CASCADE, related_name="attempt_set")
    answers = EncryptedTextField(help_text="JSON {detail_id: answer}")
    score = models.FloatField()
    per_question = models.JSONField(default=dict)  # {detail_id: score 0..1}
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
