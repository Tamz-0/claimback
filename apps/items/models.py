from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Category, Location


class Item(models.Model):
    """
    A lost report or a found report.

    IMPORTANT: this model holds only information that may be public.
    Identifying details used for ownership verification live in
    apps.vault.models.PrivateDetail, which has NO reverse relation to Item
    (related_name="+"), so `item.<anything>` can never reach them.
    """

    class Kind(models.TextChoices):
        LOST = "lost", "Lost"
        FOUND = "found", "Found"

    class Status(models.TextChoices):
        OPEN = "open", "Open"                          # lost: searching / found: reported, not yet at security desk
        IN_CUSTODY = "in_custody", "In custody"        # found item held at a security desk
        CLAIM_PENDING = "claim_pending", "Claim pending"
        CLAIM_APPROVED = "claim_approved", "Claim approved – awaiting handover"
        RETURNED = "returned", "Returned to owner"     # found item handed over
        RESOLVED = "resolved", "Resolved"              # lost report closed because item recovered
        AGEING = "ageing", "Unclaimed – ageing"
        DISPOSAL_QUEUE = "disposal_queue", "Awaiting disposal"
        DISPOSED = "disposed", "Disposed"
        WITHDRAWN = "withdrawn", "Withdrawn"

    # States in which a found item can still receive claims
    CLAIMABLE_STATES = {Status.OPEN, Status.IN_CUSTODY, Status.CLAIM_PENDING, Status.AGEING}
    # States in which an item is still "live" for matching
    ACTIVE_STATES = {Status.OPEN, Status.IN_CUSTODY, Status.CLAIM_PENDING, Status.AGEING}
    CLOSED_STATES = {Status.RETURNED, Status.RESOLVED, Status.DISPOSED, Status.WITHDRAWN}

    kind = models.CharField(max_length=5, choices=Kind.choices, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    title = models.CharField(max_length=120, help_text="Short title, e.g. 'Black HP laptop bag'")
    description = models.TextField(blank=True, help_text="Public description. Do NOT include identifying details here.")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    attributes = models.JSONField(default=dict, blank=True)  # {"colour": "black", "brand": "HP"}
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="items")
    occurred_at = models.DateTimeField("When it was lost/found", default=timezone.now, db_index=True)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_items")
    photo_public = models.BooleanField(default=True, help_text="Show the photo on the public board")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Set by the ageing job when the warning notification has been sent
    ageing_warned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            GinIndex(fields=["title"], name="item_title_trgm", opclasses=["gin_trgm_ops"]),
            models.Index(fields=["kind", "status"]),
        ]

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.title}"

    def get_absolute_url(self):
        return reverse("items:detail", args=[self.pk])

    def get_public_url(self):
        return reverse("board:detail", args=[self.pk])

    @property
    def is_found(self):
        return self.kind == self.Kind.FOUND

    @property
    def is_claimable(self):
        return self.is_found and self.status in self.CLAIMABLE_STATES

    @property
    def cover_photo(self):
        return self.photos.first()

    def attribute_text(self):
        return " ".join(str(v) for v in (self.attributes or {}).values() if v)

    def custody_started_at(self):
        first = self.custody_records.order_by("created_at").first()
        return first.created_at if first else self.created_at


def photo_path(instance, filename):
    return f"items/{timezone.now():%Y/%m}/{filename}"


class ItemPhoto(models.Model):
    """Photo of an item. Always stored AFTER metadata stripping (see imaging.py)."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=photo_path)
    thumbnail = models.ImageField(upload_to=photo_path)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    @classmethod
    def create_from_upload(cls, item, uploaded_file):
        from .imaging import sanitize_image

        full, thumb = sanitize_image(uploaded_file)
        photo = cls(item=item)
        photo.image.save(full.name, full, save=False)
        photo.thumbnail.save(thumb.name, thumb, save=False)
        photo.save()
        return photo
