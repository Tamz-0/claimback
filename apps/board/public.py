"""
The public DTO.

Everything the public board shows — HTML pages AND the /api/board/ JSON —
is built by `to_public()` below from an explicit allow-list. Templates on the
board receive these plain dicts, never Item model instances, so a template
cannot "reach through" to related data.

This module must never import apps.vault (enforced by tests/test_structure.py).
Changing PUBLIC_FIELDS is a security decision: update
docs/PUBLIC_VS_PRIVATE_FIELDS.md and get it reviewed by the security office.
"""

from apps.items.models import Item

PUBLIC_FIELDS = (
    "id", "kind", "title", "description", "category", "category_icon", "attributes",
    "location", "date", "status", "claimable", "photo", "thumbnail",
)

# Public wording for each internal status (hides internal workflow details)
PUBLIC_STATUS = {
    Item.Status.OPEN: "Open",
    Item.Status.IN_CUSTODY: "At security desk",
    Item.Status.CLAIM_PENDING: "Claim in progress",
    Item.Status.CLAIM_APPROVED: "Owner verified",
    Item.Status.RETURNED: "Returned",
    Item.Status.RESOLVED: "Resolved",
    Item.Status.AGEING: "At security desk",
    Item.Status.DISPOSAL_QUEUE: "No longer available",
    Item.Status.DISPOSED: "No longer available",
    Item.Status.WITHDRAWN: "Withdrawn",
}

# Statuses listed on the board
BOARD_STATES = [
    Item.Status.OPEN, Item.Status.IN_CUSTODY, Item.Status.CLAIM_PENDING,
    Item.Status.CLAIM_APPROVED, Item.Status.AGEING,
]
# Statuses whose public detail page can be opened (e.g. a shared link)
VIEWABLE_STATES = [s for s in Item.Status.values if s != Item.Status.WITHDRAWN]


def to_public(item: Item) -> dict:
    photo = item.cover_photo if item.photo_public else None
    data = {
        "id": item.pk,
        "kind": item.kind,
        "title": item.title,
        "description": item.description,
        "category": item.category.name,
        "category_icon": item.category.icon,
        "attributes": {str(k): str(v) for k, v in (item.attributes or {}).items()},
        "location": item.location.full_name,
        "date": item.occurred_at.date().isoformat(),
        "status": PUBLIC_STATUS.get(item.status, "Open"),
        "claimable": item.is_claimable,
        "photo": photo.image.url if photo else None,
        "thumbnail": photo.thumbnail.url if photo else None,
    }
    assert tuple(data) == PUBLIC_FIELDS, "to_public() and PUBLIC_FIELDS are out of sync"
    return data
