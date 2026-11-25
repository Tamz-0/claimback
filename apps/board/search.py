from datetime import date

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector, TrigramWordSimilarity
from django.db.models import Q
from django.db.models.functions import Greatest

from apps.catalog.models import Location
from apps.items.models import Item

from .public import BOARD_STATES


def board_queryset(params):
    """Filtered, searched queryset for the public board. `params` is a QueryDict/dict."""
    qs = (
        Item.objects.filter(status__in=BOARD_STATES)
        .select_related("category", "location", "location__parent", "location__parent__parent")
        .prefetch_related("photos")
    )
    kind = params.get("kind")
    if kind in (Item.Kind.LOST, Item.Kind.FOUND):
        qs = qs.filter(kind=kind)
    if params.get("category"):
        qs = qs.filter(category__slug=params["category"])
    loc_id = params.get("location")
    if loc_id and str(loc_id).isdigit():
        loc = Location.objects.filter(pk=loc_id).first()
        if loc:
            qs = qs.filter(location_id__in=loc.descendant_ids())
    for key, lookup in (("from", "occurred_at__date__gte"), ("to", "occurred_at__date__lte")):
        try:
            if params.get(key):
                qs = qs.filter(**{lookup: date.fromisoformat(params[key])})
        except ValueError:
            pass

    q = (params.get("q") or "").strip()[:100]
    if q:
        vector = SearchVector("title", weight="A", config="english") + SearchVector("description", weight="B", config="english")
        query = SearchQuery(q, search_type="websearch", config="english")
        qs = qs.annotate(
            rank=SearchRank(vector, query),
            sim=Greatest(TrigramWordSimilarity(q, "title"), TrigramWordSimilarity(q, "description")),
        ).filter(Q(rank__gt=0.01) | Q(sim__gt=0.35)).order_by("-rank", "-sim", "-created_at")
    else:
        qs = qs.order_by("-occurred_at", "-pk")
    return qs
