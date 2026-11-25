"""Reporting & analytics (spec section 10)."""

from statistics import median

from django.db.models import Count, F
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay

from apps.catalog.models import Location
from apps.custody.models import DisposalRecord, Handover
from apps.items.models import Item
from apps.vault.models import VerificationAttempt


def summary(start=None, end=None):
    items = Item.objects.all()
    if start:
        items = items.filter(created_at__date__gte=start)
    if end:
        items = items.filter(created_at__date__lte=end)
    found = items.filter(kind=Item.Kind.FOUND)
    lost = items.filter(kind=Item.Kind.LOST)

    found_total = found.count()
    returned = found.filter(status=Item.Status.RETURNED).count()

    handovers = Handover.objects.filter(status=Handover.Status.COMPLETED, item__in=found).select_related("item")
    durations = [(h.completed_at - h.item.created_at).total_seconds() / 3600 for h in handovers if h.completed_at]

    attempts = VerificationAttempt.objects.filter(challenge__claim__item__in=found)
    from django.conf import settings

    pass_score = settings.LOSTFOUND["CHALLENGE_PASS_SCORE"]
    attempt_total = attempts.count()
    attempt_failed = attempts.filter(score__lt=pass_score).count()

    # Hotspots: where LOST items were lost, rolled up to building level
    by_building = {}
    for loc_id, n in lost.values_list("location").annotate(n=Count("id")).values_list("location", "n"):
        loc = Location.objects.filter(pk=loc_id).first()
        name = loc.building().name if loc else "Unknown"
        by_building[name] = by_building.get(name, 0) + n
    hotspots = sorted(by_building.items(), key=lambda kv: kv[1], reverse=True)[:10]

    by_hour = dict(lost.annotate(h=ExtractHour("occurred_at")).values_list("h").annotate(n=Count("id")).values_list("h", "n"))
    by_weekday = dict(lost.annotate(d=ExtractIsoWeekDay("occurred_at")).values_list("d").annotate(n=Count("id")).values_list("d", "n"))

    categories = list(items.values(name=F("category__name"), icon=F("category__icon")).annotate(n=Count("id")).order_by("-n"))

    disposals = list(DisposalRecord.objects.filter(item__in=found).values("method").annotate(n=Count("id")).order_by("-n"))
    method_labels = dict(DisposalRecord.Method.choices)
    for d in disposals:
        d["label"] = method_labels.get(d["method"], d["method"])

    unclaimed = found.filter(status__in=[Item.Status.IN_CUSTODY, Item.Status.AGEING, Item.Status.DISPOSAL_QUEUE, Item.Status.OPEN]).count()

    return {
        "found_total": found_total,
        "lost_total": lost.count(),
        "returned": returned,
        "return_rate": round(100 * returned / found_total, 1) if found_total else 0.0,
        "lost_resolved": lost.filter(status=Item.Status.RESOLVED).count(),
        "median_hours_to_return": round(median(durations), 1) if durations else None,
        "verification_attempts": attempt_total,
        "verification_failed": attempt_failed,
        "verification_failure_rate": round(100 * attempt_failed / attempt_total, 1) if attempt_total else 0.0,
        "hotspots": hotspots,
        "by_hour": [(h, by_hour.get(h, 0)) for h in range(24)],
        "by_weekday": [(name, by_weekday.get(i + 1, 0)) for i, name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])],
        "categories": categories,
        "unclaimed": unclaimed,
        "disposed": found.filter(status=Item.Status.DISPOSED).count(),
        "disposals": disposals,
    }
