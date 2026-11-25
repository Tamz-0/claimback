import hashlib
import json

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalog.models import Location
from apps.items.models import Item


class CustodyRecord(models.Model):
    """
    One link in an item's custody chain. Append-only and hash-chained:
    each record stores the SHA-256 of the previous record, so editing or
    deleting any past record breaks verification (see verify_chain).
    """

    class Action(models.TextChoices):
        INTAKE = "intake", "Received at security desk"
        TRANSFER = "transfer", "Moved to another custody point"
        HANDOVER = "handover", "Handed over to owner"
        DISPOSAL = "disposal", "Disposed"

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="custody_records")
    action = models.CharField(max_length=10, choices=Action.choices)
    location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    from_party = models.CharField(max_length=120, blank=True, help_text="Who gave the item")
    to_party = models.CharField(max_length=120, blank=True, help_text="Who received the item")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    prev_hash = models.CharField(max_length=64, blank=True)
    hash = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ["created_at", "pk"]

    def payload(self):
        return json.dumps({
            "item": self.item_id, "action": self.action, "location": self.location_id,
            "from": self.from_party, "to": self.to_party, "actor": self.actor_id,
            "note": self.note, "at": self.created_at.isoformat(), "prev": self.prev_hash,
        }, sort_keys=True)

    def compute_hash(self):
        return hashlib.sha256(self.payload().encode()).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Custody records are append-only and cannot be edited.")
        last = CustodyRecord.objects.filter(item_id=self.item_id).order_by("-created_at", "-pk").first()
        self.prev_hash = last.hash if last else ""
        self.hash = self.compute_hash()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Custody records cannot be deleted.")

    def __str__(self):
        return f"{self.get_action_display()} – {self.item} @ {self.created_at:%Y-%m-%d %H:%M}"


def verify_chain(item):
    """Return (ok, first_bad_record_or_None)."""
    prev = ""
    for rec in CustodyRecord.objects.filter(item=item).order_by("created_at", "pk"):
        if rec.prev_hash != prev or rec.compute_hash() != rec.hash:
            return False, rec
        prev = rec.hash
    return True, None


def proof_path(instance, filename):
    return f"proof/{timezone.now():%Y/%m}/{filename}"


class Handover(models.Model):
    """Supervised handover of a found item to a verified claimant."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class Method(models.TextChoices):
        OTP = "otp", "One-time code"
        SIGNATURE = "signature", "Signature"

    claim = models.OneToOneField("claims.Claim", on_delete=models.PROTECT, related_name="handover")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="handovers")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    scheduled_for = models.DateTimeField()
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    scheduled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    otp_hash = models.CharField(max_length=64, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    method = models.CharField(max_length=10, choices=Method.choices, blank=True)
    signature = models.ImageField(upload_to=proof_path, blank=True)
    proof_photo = models.ImageField(upload_to=proof_path, blank=True)
    id_checked = models.CharField(max_length=80, blank=True, help_text="ID document checked, e.g. 'Student ID card'")
    supervised_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_for"]

    def __str__(self):
        return f"Handover of {self.item} ({self.status})"


class DisposalRecord(models.Model):
    class Method(models.TextChoices):
        DONATED = "donated", "Donated"
        RECYCLED = "recycled", "Recycled"
        DESTROYED = "destroyed", "Destroyed (e.g. ID cards, documents)"
        POLICE = "police", "Handed to police"
        AUCTIONED = "auctioned", "Auctioned"
        RETAINED = "retained", "Retained by institution"

    item = models.OneToOneField(Item, on_delete=models.PROTECT, related_name="disposal")
    method = models.CharField(max_length=10, choices=Method.choices)
    recipient = models.CharField(max_length=120, blank=True, help_text="Organisation that received it, if any")
    note = models.CharField(max_length=300, blank=True)
    proof_photo = models.ImageField(upload_to=proof_path, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.item} – {self.get_method_display()}"
