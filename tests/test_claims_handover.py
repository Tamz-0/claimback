"""
ACCEPTANCE:
* Claim requires passing the verification challenge before handover is permitted.
* Handover recorded with custody chain and proof.
* Competing claims on one item.
* Handover requires the security role.
"""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

from apps.claims import services as claims
from apps.claims.models import Claim
from apps.custody import services as custody
from apps.custody.models import CustodyRecord, Handover, verify_chain
from apps.items.models import Item

from .conftest import make_user
from .test_verification import RIGHT, answers_for


def verified_claim(item, user):
    c = claims.submit_claim(item=item, claimant=user)
    claims.answer_challenge(c, user, answers_for(c, RIGHT))
    c.refresh_from_db()
    assert c.status == Claim.Status.VERIFIED
    return c


@pytest.mark.django_db
class TestApprovalRules:
    def test_cannot_approve_unverified_claim(self, found_item, users):
        claim = claims.submit_claim(item=found_item, claimant=users["owner"])
        with pytest.raises(ValidationError):
            claims.approve_claim(claim, users["guard"])

    def test_only_security_can_approve(self, found_item, users):
        claim = verified_claim(found_item, users["owner"])
        with pytest.raises(PermissionDenied):
            claims.approve_claim(claim, users["other"])

    def test_cannot_schedule_handover_before_approval(self, found_item, users, ref):
        claim = verified_claim(found_item, users["owner"])
        with pytest.raises(ValidationError):
            custody.schedule_handover(claim, users["guard"], timezone.now(), ref["desk"])

    def test_cannot_complete_handover_if_verification_not_passed(self, found_item, users, ref, make_image):
        """Even if someone forces the claim to APPROVED in the DB, handover still checks verification."""
        claim = claims.submit_claim(item=found_item, claimant=users["owner"])
        Claim.objects.filter(pk=claim.pk).update(status=Claim.Status.APPROVED)
        claim.refresh_from_db()
        with pytest.raises(ValidationError):
            custody.schedule_handover(claim, users["guard"], timezone.now(), ref["desk"])


@pytest.mark.django_db
class TestCompetingClaims:
    def test_two_verified_claims_only_one_approved(self, found_item, users):
        second = make_user("second_owner")
        a = verified_claim(found_item, users["owner"])
        b = verified_claim(found_item, second)
        claims.approve_claim(a, users["guard"])
        b.refresh_from_db()
        assert b.status == Claim.Status.REJECTED
        assert "Another claimant" in b.decision_note
        with pytest.raises(ValidationError):
            claims.approve_claim(b, users["guard"])
        found_item.refresh_from_db()
        assert found_item.status == Item.Status.CLAIM_APPROVED

    def test_database_constraint_blocks_two_winners(self, found_item, users):
        second = make_user("second_owner")
        a = verified_claim(found_item, users["owner"])
        b = verified_claim(found_item, second)
        Claim.objects.filter(pk=a.pk).update(status=Claim.Status.APPROVED)
        with pytest.raises(IntegrityError), transaction.atomic():
            Claim.objects.filter(pk=b.pk).update(status=Claim.Status.APPROVED)

    def test_rejecting_last_claim_reopens_item(self, found_item, users, ref):
        custody.record_intake(found_item, users["guard"], ref["desk"])
        c = claims.submit_claim(item=found_item, claimant=users["owner"])
        found_item.refresh_from_db()
        assert found_item.status == Item.Status.CLAIM_PENDING
        claims.reject_claim(c, users["guard"])
        found_item.refresh_from_db()
        assert found_item.status == Item.Status.IN_CUSTODY


@pytest.mark.django_db
class TestHandover:
    def _approved(self, found_item, users, ref):
        custody.record_intake(found_item, users["guard"], ref["desk"])
        claim = verified_claim(found_item, users["owner"])
        claims.approve_claim(claim, users["guard"])
        handover, otp = custody.schedule_handover(claim, users["guard"], timezone.now(), ref["desk"])
        return claim, handover, otp

    def test_full_handover_with_otp_records_custody_and_proof(self, found_item, users, ref, make_image):
        claim, handover, otp = self._approved(found_item, users, ref)
        custody.complete_handover(handover, users["guard"], proof_photo=make_image(), otp=otp, id_checked="Student ID")
        handover.refresh_from_db()
        found_item.refresh_from_db()
        claim.refresh_from_db()
        assert handover.status == Handover.Status.COMPLETED and handover.method == Handover.Method.OTP
        assert handover.proof_photo and handover.supervised_by == users["guard"]
        assert claim.status == Claim.Status.HANDED_OVER
        assert found_item.status == Item.Status.RETURNED
        actions = list(found_item.custody_records.values_list("action", flat=True))
        assert actions == [CustodyRecord.Action.INTAKE, CustodyRecord.Action.HANDOVER]
        assert verify_chain(found_item) == (True, None)

    def test_handover_requires_security_role(self, found_item, users, ref, make_image):
        _claim, handover, otp = self._approved(found_item, users, ref)
        for user in (users["owner"], users["finder"], users["other"]):
            with pytest.raises(PermissionDenied):
                custody.complete_handover(handover, user, proof_photo=make_image(), otp=otp)
        # and through the web UI
        c = Client()
        c.force_login(users["other"])
        assert c.get(f"/desk/handover/{handover.pk}/").status_code == 403
        assert c.post(f"/desk/handover/{handover.pk}/", {"otp": otp}).status_code == 403
        assert c.post(f"/api/handovers/{handover.pk}/complete/", {"otp": otp}).status_code == 403

    def test_handover_requires_proof_photo(self, found_item, users, ref):
        _c, handover, otp = self._approved(found_item, users, ref)
        with pytest.raises(ValidationError):
            custody.complete_handover(handover, users["guard"], proof_photo=None, otp=otp)

    def test_wrong_otp_is_counted_and_rejected(self, found_item, users, ref, make_image):
        _c, handover, otp = self._approved(found_item, users, ref)
        wrong = "000000" if otp != "000000" else "111111"
        with pytest.raises(ValidationError):
            custody.complete_handover(handover, users["guard"], proof_photo=make_image(), otp=wrong)
        handover.refresh_from_db()
        assert handover.otp_attempts == 1 and handover.status == Handover.Status.SCHEDULED

    def test_signature_instead_of_otp(self, found_item, users, ref, make_image):
        from django.core.files.base import ContentFile

        _c, handover, _otp = self._approved(found_item, users, ref)
        sig = ContentFile(make_image("s.png").read(), name="sig.png")
        custody.complete_handover(handover, users["guard"], proof_photo=make_image(), signature_file=sig)
        handover.refresh_from_db()
        assert handover.method == Handover.Method.SIGNATURE and handover.signature

    def test_otp_not_returned_by_api(self, found_item, users, ref):
        custody.record_intake(found_item, users["guard"], ref["desk"])
        claim = verified_claim(found_item, users["owner"])
        claims.approve_claim(claim, users["guard"])
        c = Client()
        c.force_login(users["guard"])
        resp = c.post("/api/handovers/", {"claim": claim.pk, "scheduled_for": timezone.now().isoformat(),
                                          "location": ref["desk"].pk})
        assert resp.status_code == 201, resp.content
        assert "otp" not in resp.content.decode().lower()


@pytest.mark.django_db
class TestCustodyChain:
    def test_records_are_append_only(self, found_item, users, ref):
        rec = custody.record_intake(found_item, users["guard"], ref["desk"])
        with pytest.raises(ValueError):
            rec.note = "edited"
            rec.save()
        with pytest.raises(ValueError):
            rec.delete()

    def test_tampering_is_detected(self, found_item, users, ref):
        custody.record_intake(found_item, users["guard"], ref["desk"])
        custody.record_intake(found_item, users["guard"], ref["library_desk"])
        assert verify_chain(found_item)[0]
        first = found_item.custody_records.first()
        CustodyRecord.objects.filter(pk=first.pk).update(to_party="someone else")   # bypass the model
        ok, bad = verify_chain(found_item)
        assert not ok and bad.pk == first.pk

    def test_only_security_records_intake(self, found_item, users, ref):
        with pytest.raises(PermissionDenied):
            custody.record_intake(found_item, users["finder"], ref["desk"])
