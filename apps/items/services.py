from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import audit

from .models import Item, ItemPhoto


@transaction.atomic
def create_report(*, reporter, kind, title, description, category, location, occurred_at,
                  attributes=None, photos=(), private_pairs=(), photo_public=True):
    """
    Create a lost/found report in one transaction:
    item + sanitised photos + encrypted private details, then queue matching.
    """
    from apps.vault.services import store_private_details

    pairs = [(q, a) for q, a in private_pairs if (q or "").strip() and (a or "").strip()]
    minimum = settings.LOSTFOUND["MIN_PRIVATE_DETAILS"]
    if kind == Item.Kind.FOUND and len(pairs) < minimum:
        raise ValidationError(
            f"Please record at least {minimum} hidden identifying details. "
            "They are never shown publicly and are used to check the real owner."
        )

    item = Item.objects.create(
        reporter=reporter, kind=kind, title=title.strip(), description=description.strip(),
        category=category, location=location, occurred_at=occurred_at,
        attributes={k: v.strip() for k, v in (attributes or {}).items() if v and v.strip()},
        photo_public=photo_public,
    )
    for f in photos:
        ItemPhoto.create_from_upload(item, f)
    if pairs:
        store_private_details(item, pairs)

    audit(reporter, f"item.reported_{kind}", item, category=category.slug, location=location.pk)
    transaction.on_commit(lambda: _match_safely(item.pk))
    return item


def _match_safely(item_id):
    """Matching must never break report submission."""
    import logging

    from apps.matching.engine import refresh_matches_for

    try:
        item = Item.objects.select_related("location", "category").get(pk=item_id)
        refresh_matches_for(item)
    except Exception:  # pragma: no cover
        logging.getLogger(__name__).exception("Matching failed for item %s", item_id)


@transaction.atomic
def withdraw(item, user):
    if item.reporter_id != user.pk:
        raise ValidationError("Only the reporter can withdraw this report.")
    if item.kind == Item.Kind.FOUND and item.status != Item.Status.OPEN:
        raise ValidationError("This item is already with security; ask the security desk to close it.")
    if item.status in Item.CLOSED_STATES:
        raise ValidationError("This report is already closed.")
    item.status = Item.Status.WITHDRAWN if item.kind == Item.Kind.FOUND else Item.Status.RESOLVED
    item.save(update_fields=["status", "updated_at"])
    audit(user, "item.withdrawn", item)
    return item
