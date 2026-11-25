"""
Matching engine (M3): text, attribute, location and time-proximity matching.

For a lost item L and a candidate found item F:

    score = 0.25 * category      same category -> 1, else 0
          + 0.20 * attributes    share of attributes that agree (colour, brand…)
          + 0.30 * text          PostgreSQL trigram similarity + full-text rank
          + 0.15 * location      closeness in the campus location tree
          + 0.10 * time          found soon after it was lost -> 1, decays over 30 days

Text similarity runs inside PostgreSQL (pg_trgm + full-text search), so the
database does the heavy lifting. Image similarity is intentionally NOT used
in v1 (see spec section 7).
"""

import re
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector, TrigramSimilarity, TrigramWordSimilarity
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Greatest

from apps.items.models import Item

from .models import MatchSuggestion

WEIGHTS = {"category": 0.25, "attributes": 0.20, "text": 0.30, "location": 0.15, "time": 0.10}
CFG = settings.LOSTFOUND
STOP = {"a", "an", "the", "and", "or", "of", "with", "in", "on", "at", "near", "my", "lost", "found", "for", "to", "is", "it"}


SPELLING = {"grey": "gray", "colour": "color", "golden": "gold", "silvery": "silver", "transparent": "clear"}


def _norm(v):
    words = re.sub(r"[^a-z0-9]+", " ", str(v).lower()).split()
    return " ".join(SPELLING.get(w, w) for w in words)


def attribute_score(a: dict, b: dict) -> float:
    keys = [k for k in set(a or {}) & set(b or {}) if _norm(a[k]) and _norm(b[k])]
    if not keys:
        return 0.5  # unknown: neutral
    agree = 0.0
    for k in keys:
        x, y = _norm(a[k]), _norm(b[k])
        if x == y:
            agree += 1
        elif set(x.split()) & set(y.split()):
            agree += 0.6
    return agree / len(keys)


def location_score(loc_a, loc_b) -> float:
    if loc_a.pk == loc_b.pk:
        return 1.0
    a, b = loc_a.ancestor_ids(), loc_b.ancestor_ids()
    if loc_a.pk in b or loc_b.pk in a:      # one contains the other (building vs room in it)
        return 0.85
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    depth = max(len(a), len(b))
    # 1 shared level (same campus only) -> low; share building -> high
    return round({0: 0.0, 1: 0.15}.get(common, 0.15 + 0.7 * (common - 1) / max(depth - 1, 1)), 3)


def time_score(lost_at, found_at) -> float:
    delta = (found_at - lost_at).total_seconds() / 86400
    if delta < -1:
        return 0.0          # found well before it was lost: impossible
    if delta <= 2:
        return 1.0
    return max(0.0, 1 - (delta - 2) / 28)


def _tsquery(text):
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", text.lower()) if w not in STOP and len(w) > 1]
    return " | ".join(dict.fromkeys(words)) if words else None


def candidates_for(item):
    """Opposite-kind active items within the time window, with DB-side text similarity."""
    window = timedelta(days=CFG["MATCH_WINDOW_DAYS"])
    other_kind = Item.Kind.FOUND if item.kind == Item.Kind.LOST else Item.Kind.LOST
    qs = Item.objects.filter(kind=other_kind, status__in=Item.ACTIVE_STATES).exclude(reporter=item.reporter)
    if item.kind == Item.Kind.LOST:
        qs = qs.filter(occurred_at__gte=item.occurred_at - timedelta(days=1), occurred_at__lte=item.occurred_at + window)
    else:
        qs = qs.filter(occurred_at__lte=item.occurred_at + timedelta(days=1), occurred_at__gte=item.occurred_at - window)

    text = f"{item.title} {item.description} {item.attribute_text()}"
    qs = qs.annotate(
        t_title=TrigramSimilarity("title", item.title),
        t_word=Greatest(TrigramWordSimilarity(item.title, "description"), TrigramWordSimilarity(item.title, "title")),
    )
    raw = _tsquery(text)
    if raw:
        vector = SearchVector("title", weight="A", config="english") + SearchVector("description", weight="B", config="english")
        qs = qs.annotate(rank=SearchRank(vector, SearchQuery(raw, search_type="raw", config="english")))
    # Cheap pre-filter: same category OR some textual overlap
    cond = Q(category=item.category) | Q(t_title__gt=0.15) | Q(t_word__gt=0.3)
    if raw:
        cond |= Q(rank__gt=0.05)
    return qs.filter(cond).select_related("location", "category")[:200]


def score_pair(lost, found, t_title=0.0, t_word=0.0, rank=0.0):
    text = min(1.0, 0.45 * t_title + 0.30 * t_word + 0.25 * min(1.0, (rank or 0) * 2.5))
    parts = {
        "category": 1.0 if lost.category_id == found.category_id else 0.0,
        "attributes": attribute_score(lost.attributes, found.attributes),
        "text": round(text, 3),
        "location": location_score(lost.location, found.location),
        "time": round(time_score(lost.occurred_at, found.occurred_at), 3),
    }
    if parts["time"] == 0.0:
        return 0.0, parts
    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    return round(total, 3), parts


@transaction.atomic
def refresh_matches_for(item, notify=True):
    """(Re)compute suggestions for one item. Returns list of MatchSuggestion."""
    if item.status not in Item.ACTIVE_STATES:
        return []
    results = []
    for cand in candidates_for(item):
        lost, found = (item, cand) if item.kind == Item.Kind.LOST else (cand, item)
        score, parts = score_pair(lost, found, cand.t_title, cand.t_word, getattr(cand, "rank", 0.0))
        if score >= CFG["MATCH_THRESHOLD"]:
            results.append((score, parts, lost, found))
    results.sort(key=lambda r: r[0], reverse=True)
    saved = []
    for score, parts, lost, found in results[: CFG["MATCH_MAX_PER_ITEM"]]:
        m, created = MatchSuggestion.objects.get_or_create(
            lost=lost, found=found, defaults={"score": score, "breakdown": parts}
        )
        if not created and m.status == MatchSuggestion.Status.SUGGESTED:
            m.score, m.breakdown = score, parts
            m.save(update_fields=["score", "breakdown", "updated_at"])
        saved.append(m)
        if notify and created and not m.notified:
            _notify_owner(m)
    return saved


def _notify_owner(match):
    from apps.audit.models import Notification
    from apps.audit.services import notify

    notify(
        match.lost.reporter, Notification.Kind.MATCH_FOUND,
        f"A found item may match your lost report “{match.lost.title}”: {match.found.title}.",
        url=match.lost.get_absolute_url(),
    )
    match.notified = True
    match.save(update_fields=["notified"])


def refresh_all():
    """Nightly job: refresh suggestions for every active lost report."""
    count = 0
    for item in Item.objects.filter(kind=Item.Kind.LOST, status__in=Item.ACTIVE_STATES).select_related("location", "category"):
        count += len(refresh_matches_for(item))
    # Drop suggestions where either side is no longer active
    MatchSuggestion.objects.filter(status=MatchSuggestion.Status.SUGGESTED).filter(
        Q(lost__status__in=Item.CLOSED_STATES) | Q(found__status__in=Item.CLOSED_STATES)
    ).delete()
    return count
