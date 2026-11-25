"""
ACCEPTANCE: "Private details never appear in any public response – proven exhaustively."

For EVERY item status, and for EVERY public endpoint (HTML board, board
fragment used for infinite scroll, item page, search, JSON API), as both an
anonymous visitor and an unrelated logged-in user, assert that none of the
canary strings planted in the item's private details appear in the response,
and that no private-looking key appears in JSON.

Claimant-facing pages are also checked: the claimant may see the QUESTIONS
during the challenge, but must never see the ANSWERS.
"""

import json

import pytest
from django.test import Client

from apps.claims import services as claims
from apps.items.models import Item

from .conftest import CANARIES, CANARY_A, CANARY_A2

ANSWER_CANARIES = ["CANARYA9b1c", "CANARYA5c6e", "zebra striped", "grandmother in red saree", "dried flower"]
FORBIDDEN_JSON_KEYS = {"private", "private_details", "answer", "answers", "question", "questions", "detail_ids",
                       "reporter", "email", "phone", "otp", "otp_hash"}


def public_urls(item):
    return [
        ("/", {}),
        ("/?q=iphone", {}),
        ("/?kind=found&category=phone", {}),
        (f"/?location={item.location.parent_id}", {}),
        ("/?page=1", {"HTTP_HX_REQUEST": "true"}),
        (f"/item/{item.pk}/", {}),
        ("/api/board/", {}),
        ("/api/board/?q=iphone", {}),
        (f"/api/board/{item.pk}/", {}),
    ]


def walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_keys(v)


def assert_clean(resp, canaries=CANARIES, forbidden_keys=FORBIDDEN_JSON_KEYS):
    body = resp.content.decode("utf-8", errors="replace")
    for c in canaries:
        assert c.lower() not in body.lower(), f"LEAK: '{c}' found in {resp.request['PATH_INFO']} ({resp.status_code})"
    if resp.get("Content-Type", "").startswith("application/json") and resp.status_code == 200:
        keys = {str(k).lower() for k in walk_keys(json.loads(body))}
        assert not keys & forbidden_keys, f"Private key(s) {keys & forbidden_keys} in JSON"


@pytest.mark.django_db
@pytest.mark.parametrize("status", [s for s in Item.Status.values])
def test_no_private_field_on_public_endpoints_in_any_state(status, found_item, users):
    Item.objects.filter(pk=found_item.pk).update(status=status)
    found_item.refresh_from_db()
    anon = Client()
    logged_in = Client()
    logged_in.force_login(users["other"])
    checked = 0
    for client in (anon, logged_in):
        for url, headers in public_urls(found_item):
            resp = client.get(url, **headers)
            assert resp.status_code in (200, 404), (url, resp.status_code)
            assert_clean(resp)
            checked += 1
    assert checked == 2 * len(public_urls(found_item))


@pytest.mark.django_db
def test_no_leak_through_full_real_workflow(found_item, users, ref, make_image):
    """Drive the item through real transitions and check public endpoints after each step."""
    from apps.custody import services as custody

    anon = Client()

    def check():
        for url, headers in public_urls(found_item):
            assert_clean(anon.get(url, **headers))

    check()                                                   # open
    custody.record_intake(found_item, users["guard"], ref["desk"])
    check()                                                   # in custody
    claim = claims.submit_claim(item=found_item, claimant=users["owner"])
    check()                                                   # claim pending
    from apps.vault.services import challenge_questions

    q = dict(challenge_questions(claim.challenge))
    expected = {"CANARYQ7f3a": CANARY_A, "CANARYQ2e4d": CANARY_A2, "Case?": "clear case with dried flower"}
    answers = {str(pk): next(v for k, v in expected.items() if text.startswith(k)) for pk, text in q.items()}
    claims.answer_challenge(claim, users["owner"], answers)
    claim.refresh_from_db()
    assert claim.status == claim.Status.VERIFIED
    claims.approve_claim(claim, users["guard"])
    check()                                                   # approved
    from django.utils import timezone

    handover, otp = custody.schedule_handover(claim, users["guard"], timezone.now(), ref["desk"])
    custody.complete_handover(handover, users["guard"], proof_photo=make_image(), otp=otp)
    check()                                                   # returned


@pytest.mark.django_db
def test_claimant_never_sees_answers(found_item, users):
    claim = claims.submit_claim(item=found_item, claimant=users["owner"])
    c = Client()
    c.force_login(users["owner"])
    for url in (f"/claims/{claim.pk}/", "/api/claims/", f"/api/claims/{claim.pk}/", "/me/?mine=1", "/notifications/"):
        resp = c.get(url)
        assert resp.status_code == 200, url
        # The claimant may see the questions (that is the challenge) but never answers.
        assert_clean(resp, ANSWER_CANARIES, forbidden_keys={"answer", "answers", "expected", "detail_ids"})
    # Wrong answers -> still no answers revealed
    c.post(f"/claims/{claim.pk}/", {f"answer_{pk}": "wrong" for pk in claim.challenge.detail_ids})
    assert_clean(c.get(f"/claims/{claim.pk}/"), ANSWER_CANARIES)


@pytest.mark.django_db
def test_unrelated_user_cannot_open_private_item_page(found_item, users):
    c = Client()
    c.force_login(users["other"])
    resp = c.get(f"/items/{found_item.pk}/", follow=True)
    assert_clean(resp)
    resp = c.get(f"/api/items/{found_item.pk}/")
    assert resp.status_code == 404
    resp = c.get(f"/desk/item/{found_item.pk}/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_reporting_api_does_not_echo_private_details(ref, users):
    c = Client()
    c.force_login(users["finder"])
    resp = c.post("/api/items/", data=json.dumps({
        "kind": "found", "title": "Brown wallet", "category": "wallet-purse", "location": ref["room"].pk,
        "private_details": [{"question": "CANARYQ7f3a cash?", "answer": "CANARYA9b1c 500"},
                            {"question": "CANARYQ2e4d cards?", "answer": "CANARYA5c6e SBI"}],
    }), content_type="application/json")
    assert resp.status_code == 201, resp.content
    assert_clean(resp)
    assert_clean(c.get(f"/api/items/{resp.json()['id']}/"))
