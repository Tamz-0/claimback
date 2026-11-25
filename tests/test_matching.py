"""ACCEPTANCE: match suggestions returned for at least 70% of seeded matching pairs."""

import pytest

from apps.accounts.models import User
from apps.dashboard import demo_data, seeding
from apps.matching.engine import attribute_score, location_score, refresh_all, time_score
from apps.matching.models import MatchSuggestion


@pytest.mark.django_db
def test_seeded_pairs_match_rate_at_least_70_percent(ref):
    owner = User.objects.create(username="o")
    finder = User.objects.create(username="f")
    other = User.objects.create(username="x")
    pairs = seeding.seed_match_pairs(owner, finder)
    seeding.seed_distractors(other)
    refresh_all()

    hits, top1 = 0, 0
    for lost, found in pairs:
        suggested = list(MatchSuggestion.objects.filter(lost=lost).order_by("-score").values_list("found_id", flat=True))
        if found.pk in suggested[:5]:
            hits += 1
        if suggested and suggested[0] == found.pk:
            top1 += 1
    rate = hits / len(pairs)
    print(f"\nMatch rate (top-5): {hits}/{len(pairs)} = {rate:.0%}; top-1: {top1}/{len(pairs)}")
    assert len(pairs) == len(demo_data.MATCH_PAIRS) >= 20
    assert rate >= 0.70


@pytest.mark.django_db
def test_suggestions_generated_on_report_creation(ref, users, found_item, django_capture_on_commit_callbacks):
    from django.utils import timezone

    from apps.items.models import Item
    from apps.items.services import create_report

    with django_capture_on_commit_callbacks(execute=True):
        lost = create_report(reporter=users["owner"], kind=Item.Kind.LOST, title="Lost black iPhone",
                             description="Apple phone", category=ref["phone"], location=ref["room"],
                             occurred_at=timezone.now() - timezone.timedelta(hours=5), attributes={"colour": "black"})
    assert MatchSuggestion.objects.filter(lost=lost, found=found_item).exists()
    assert users["owner"].notifications.filter(kind="match_found").exists()


@pytest.mark.django_db
def test_no_match_when_found_long_before_lost(ref, users, found_item):
    from django.utils import timezone

    from apps.items.models import Item
    from apps.items.services import create_report
    from apps.matching.engine import refresh_matches_for

    lost = create_report(reporter=users["owner"], kind=Item.Kind.LOST, title="Black Apple iPhone",
                         description="", category=ref["phone"], location=ref["room"],
                         occurred_at=found_item.occurred_at + timezone.timedelta(days=3))  # lost AFTER it was found
    refresh_matches_for(lost, notify=False)
    assert not MatchSuggestion.objects.filter(lost=lost, found=found_item).exists()


def test_component_scores():
    assert attribute_score({"colour": "Grey"}, {"colour": "gray"}) == 1.0
    assert attribute_score({"colour": "red"}, {"colour": "blue"}) == 0.0
    from datetime import datetime, timedelta

    t = datetime(2026, 1, 1)
    assert time_score(t, t + timedelta(hours=5)) == 1.0
    assert time_score(t, t - timedelta(days=3)) == 0.0
    assert 0 < time_score(t, t + timedelta(days=10)) < 1


@pytest.mark.django_db
def test_location_score_tree(ref):
    from apps.catalog.models import Location

    a204 = Location.objects.get(name="Room A-204")
    a101 = Location.objects.get(name="Room A-101")
    block_a = a204.parent
    gym = Location.objects.get(name="Gym")
    assert location_score(a204, a204) == 1.0
    assert location_score(a204, block_a) == 0.85
    assert location_score(a204, gym) < location_score(a204, a101)
