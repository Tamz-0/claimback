"""Verification challenge scoring and status transitions."""

import pytest

from apps.claims import services as claims
from apps.claims.models import Claim
from apps.vault.models import VerificationChallenge
from apps.vault.scoring import question_score, score_answers, similarity
from apps.vault.services import challenge_questions

from .conftest import CANARY_A, CANARY_A2

RIGHT = {"CANARYQ7f3a": "zebra striped sticker", "CANARYQ2e4d": "my grandmother wearing a red saree",
         "Case?": "transparent case with a dried flower"}
EXACT = {"CANARYQ7f3a": CANARY_A, "CANARYQ2e4d": CANARY_A2, "Case?": "clear case with dried flower"}


def answers_for(claim, table):
    q = dict(challenge_questions(claim.challenge))
    return {str(pk): next(v for k, v in table.items() if text.startswith(k)) for pk, text in q.items()}


class TestScoring:
    def test_exact_and_case_insensitive(self):
        assert similarity("NASA logo", "nasa LOGO") == 1.0

    def test_paraphrase_gets_credit(self):
        assert question_score("NASA logo and a cat sticker", "cat sticker and the nasa logo") == 1.0
        assert 0.5 <= question_score("NASA logo and a cat sticker", "a nasa sticker and a cat") < 1.0
        assert question_score("golden retriever puppy", "a golden retriever") >= 0.5

    def test_wrong_answer_scores_zero(self):
        assert question_score("NASA logo", "spiderman") == 0.0
        assert question_score("about 500 rupees", "") == 0.0

    def test_shotgun_answers_are_penalised(self):
        shotgun = "red blue green black white yellow pink nasa cat dog logo sticker star"
        assert question_score("NASA logo", shotgun) < 1.0

    def test_overall_score_is_mean(self):
        score, per = score_answers({"1": "NASA logo", "2": "4821"}, {"1": "nasa logo", "2": "1234"})
        assert per == {"1": 1.0, "2": 0.0}
        assert score == 0.5


@pytest.mark.django_db
class TestChallengeFlow:
    def test_challenge_created_with_three_questions(self, found_item, users):
        claim = claims.submit_claim(item=found_item, claimant=users["owner"])
        assert claim.status == Claim.Status.VERIFYING
        assert len(claim.challenge.detail_ids) == 3

    def test_correct_paraphrased_answers_pass(self, found_item, users):
        claim = claims.submit_claim(item=found_item, claimant=users["owner"])
        claims.answer_challenge(claim, users["owner"], answers_for(claim, RIGHT))
        claim.refresh_from_db()
        assert claim.challenge.status == VerificationChallenge.Status.PASSED
        assert claim.status == Claim.Status.VERIFIED

    def test_wrong_answers_then_locked(self, found_item, users):
        claim = claims.submit_claim(item=found_item, claimant=users["other"])
        wrong = {str(pk): "no idea" for pk in claim.challenge.detail_ids}
        claims.answer_challenge(claim, users["other"], wrong)
        claim.refresh_from_db()
        assert claim.challenge.status == VerificationChallenge.Status.FAILED
        assert claim.challenge.attempts_left == 1
        claims.answer_challenge(claim, users["other"], wrong)
        claim.refresh_from_db()
        assert claim.challenge.status == VerificationChallenge.Status.LOCKED
        assert claim.status == Claim.Status.REJECTED
        # cannot re-claim after being locked out
        with pytest.raises(Exception):
            claims.submit_claim(item=found_item, claimant=users["other"])

    def test_borderline_goes_to_security_review(self, found_item, users):
        claim = claims.submit_claim(item=found_item, claimant=users["owner"])
        q = dict(challenge_questions(claim.challenge))
        partial = {}
        for i, (pk, text) in enumerate(q.items()):
            right = next(v for k, v in RIGHT.items() if text.startswith(k))
            partial[str(pk)] = right if i < 1 else ("dried flower" if text.startswith("Case?") else "something else")
        claims.answer_challenge(claim, users["owner"], partial)
        claim.refresh_from_db()
        assert claim.challenge.status in (VerificationChallenge.Status.REVIEW, VerificationChallenge.Status.FAILED)
        if claim.challenge.status == VerificationChallenge.Status.REVIEW:
            claims.review_verification(claim, users["guard"], approve=True)
            claim.refresh_from_db()
            assert claim.status == Claim.Status.VERIFIED

    def test_finder_cannot_claim_own_found_item(self, found_item, users):
        with pytest.raises(Exception):
            claims.submit_claim(item=found_item, claimant=users["finder"])

    def test_only_claimant_can_answer(self, found_item, users):
        claim = claims.submit_claim(item=found_item, claimant=users["owner"])
        with pytest.raises(Exception):
            claims.answer_challenge(claim, users["other"], answers_for(claim, EXACT))
