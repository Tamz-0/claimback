"""
The ONLY module allowed to read PrivateDetail rows.

Everything returned to claimants contains questions only, never answers.
"""

import json
import random

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PrivateDetail, VerificationAttempt, VerificationChallenge
from .scoring import score_answers

CFG = settings.LOSTFOUND


class VaultError(Exception):
    pass


# --- Writing details (by the reporter of a found item) ----------------------

def store_private_details(item, pairs):
    """pairs: iterable of (question, answer). Blank rows are skipped."""
    created = []
    for question, answer in pairs:
        question, answer = (question or "").strip(), (answer or "").strip()
        if question and answer:
            created.append(PrivateDetail.vault.create(item=item, question=question[:300], answer=answer[:300]))
    return created


def count_private_details(item):
    return PrivateDetail.vault.filter(item=item).count()


def details_for_owner_view(item, user):
    """The reporter (and security) may see the details they entered."""
    from apps.accounts.roles import is_security

    if item.reporter_id != user.pk and not is_security(user):
        raise VaultError("Not allowed to view private details for this item.")
    return list(PrivateDetail.vault.filter(item=item).values("id", "question", "answer"))


# --- Challenges ---------------------------------------------------------------

def create_challenge(claim):
    """Pick N random hidden details for this claim."""
    ids = list(PrivateDetail.vault.filter(item=claim.item).values_list("id", flat=True))
    if not ids:
        raise VaultError("This item has no private details recorded; security must verify in person.")
    picked = random.sample(ids, min(CFG["CHALLENGE_QUESTIONS"], len(ids)))
    return VerificationChallenge.objects.create(
        claim=claim, detail_ids=picked, max_attempts=CFG["CHALLENGE_MAX_ATTEMPTS"]
    )


def challenge_questions(challenge):
    """[(detail_id, question)] — questions only, NEVER answers."""
    rows = {d.pk: d.question for d in PrivateDetail.vault.filter(pk__in=challenge.detail_ids)}
    return [(pk, rows[pk]) for pk in challenge.detail_ids if pk in rows]


@transaction.atomic
def submit_answers(challenge, answers: dict):
    """
    Score an attempt and update challenge status.
    answers: {detail_id: text}. Returns the VerificationAttempt.
    """
    challenge = VerificationChallenge.objects.select_for_update().get(pk=challenge.pk)
    if not challenge.can_answer:
        raise VaultError("No attempts left for this challenge.")

    expected = {str(d.pk): d.answer for d in PrivateDetail.vault.filter(pk__in=challenge.detail_ids)}
    given = {str(k): (v or "")[:300] for k, v in answers.items() if str(k) in expected}
    score, per = score_answers(expected, given)

    attempt = VerificationAttempt.objects.create(
        challenge=challenge, answers=json.dumps(given), score=score, per_question=per
    )
    challenge.attempts += 1
    challenge.best_score = max(score, challenge.best_score or 0)
    if score >= CFG["CHALLENGE_PASS_SCORE"]:
        challenge.status = VerificationChallenge.Status.PASSED
    elif score >= CFG["CHALLENGE_REVIEW_SCORE"]:
        challenge.status = VerificationChallenge.Status.REVIEW
    elif challenge.attempts >= challenge.max_attempts:
        challenge.status = VerificationChallenge.Status.LOCKED
    else:
        challenge.status = VerificationChallenge.Status.FAILED
    challenge.save()
    return attempt


def review_data(challenge, reviewer):
    """For security reviewers: questions, expected answers and the claimant's answers."""
    from apps.accounts.roles import is_security

    if not is_security(reviewer):
        raise VaultError("Only security personnel can review verification answers.")
    details = {d.pk: d for d in PrivateDetail.vault.filter(pk__in=challenge.detail_ids)}
    attempts = []
    for a in challenge.attempt_set.all():
        given = json.loads(a.answers)
        attempts.append({
            "created_at": a.created_at,
            "score": a.score,
            "rows": [
                {"question": details[pk].question, "expected": details[pk].answer,
                 "given": given.get(str(pk), ""), "score": a.per_question.get(str(pk), 0)}
                for pk in challenge.detail_ids if pk in details
            ],
        })
    return attempts


@transaction.atomic
def security_decision(challenge, reviewer, approve: bool):
    if challenge.status != VerificationChallenge.Status.REVIEW:
        raise VaultError("Only challenges awaiting review can be decided.")
    challenge.status = VerificationChallenge.Status.PASSED if approve else VerificationChallenge.Status.REJECTED
    challenge.reviewed_by = reviewer
    challenge.reviewed_at = timezone.now()
    challenge.save()
    return challenge
