from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    """Item category, e.g. Electronics > Phone. Configured by Campus Administrators."""

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True, blank=True)
    icon = models.CharField(max_length=8, blank=True, help_text="Emoji shown on the board")
    # Attribute keys the reporting form asks for, e.g. ["colour", "brand"].
    attributes = models.JSONField(default=list, blank=True, help_text='List of attribute names, e.g. ["colour", "brand"]')
    # Suggested hidden-detail questions shown to whoever reports a found item.
    verification_prompts = models.JSONField(
        default=list, blank=True, help_text="Suggested private questions, e.g. 'What is the lock-screen wallpaper?'"
    )
    retention_days = models.PositiveIntegerField(default=90, help_text="Days an unclaimed item is kept before disposal")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.icon} {self.name}".strip()


class Location(models.Model):
    """Campus location tree: Campus > Building > Floor/Area > Room."""

    class Kind(models.TextChoices):
        CAMPUS = "campus", "Campus"
        BUILDING = "building", "Building"
        AREA = "area", "Floor / Area"
        ROOM = "room", "Room"

    name = models.CharField(max_length=100)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.BUILDING)
    # Position on the campus map image, in percent (0-100) of width/height.
    map_x = models.FloatField(null=True, blank=True)
    map_y = models.FloatField(null=True, blank=True)
    is_custody_point = models.BooleanField(default=False, help_text="Security desk where found items are stored")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("parent", "name")]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return " › ".join(loc.name for loc in self.lineage() if loc.kind != self.Kind.CAMPUS) or self.name

    def lineage(self):
        """List of locations from the root down to self."""
        chain, node, seen = [], self, set()
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    def ancestor_ids(self):
        return [loc.pk for loc in self.lineage()]

    def building(self):
        for loc in self.lineage():
            if loc.kind == self.Kind.BUILDING:
                return loc
        return self

    def descendant_ids(self):
        ids, frontier = [self.pk], [self.pk]
        while frontier:
            frontier = list(Location.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
            ids.extend(frontier)
        return ids
