"""
Claim workflow (M5). Rules enforced here, not in views:

* A claim always starts with a verification challenge (hidden details).
* A claim can only be APPROVED once its challenge has PASSED.
* Only one claim per item can be approved; approving rejects all competitors.
* Only security personnel can approve/reject.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.roles import is_security
from apps.audit.models import Notification
from apps.audit.services import audit, notify
from apps.items.models import Item
from apps.vault import services as vault
from apps.vault.models import VerificationChallenge

from .models import Claim


@transaction.atomic
def submit_claim(*, item, claimant, statement="", lost_report=None):
    item = Item.objects.select_for_update().get(pk=item.pk)
    if not item.is_claimable:
        raise ValidationError("This item is not open for claims.")
    if item.reporter_id == claimant.pk:
        raise ValidationError("You reported this item as found, so you cannot claim it.")
    if Claim.objects.filter(item=item, claimant=claimant, status__in=Claim.OPEN_STATES).exists():
        raise ValidationError("You already have an open claim on this item.")
    if Claim.objects.filter(item=item, claimant=claimant, challenge__status=VerificationChallenge.Status.LOCKED).exists():
        raise ValidationError("You used all verification attempts on this item. Please visit the security desk.")
    if lost_report and (lost_report.reporter_id != claimant.pk or lost_report.kind != Item.Kind.LOST):
        lost_report = None

    claim = Claim.objects.create(item=item, claimant=claimant, statement=statement.strip(), lost_report=lost_report)
    try:
        vault.create_challenge(claim)
    except vault.VaultError:
        # No hidden details recorded: security must verify in person.
        claim.status = Claim.Status.REVIEW
        claim.save(update_fields=["status"])

    if item.status != Item.Status.CLAIM_PENDING:
        item.status = Item.Status.CLAIM_PENDING
        item.save(update_fields=["status", "updated_at"])

    audit(claimant, "claim.submitted", claim, item=item.pk)
    notify(item.reporter, Notification.Kind.CLAIM_SUBMITTED,
           f"Someone has claimed the item you found: “{item.title}”. Security will verify ownership.",
           url=item.get_absolute_url())
    notify(claimant, Notification.Kind.VERIFICATION_REQUIRED,
           f"Answer the verification questions to prove “{item.title}” is yours.", url=claim.get_absolute_url())
    return claim


@transaction.atomic
def answer_challenge(claim, user, answers):
    if claim.claimant_id != user.pk:
        raise PermissionDenied
    if claim.status != Claim.Status.VERIFYING:
        raise ValidationError("This claim is not awaiting verification.")
    attempt = vault.submit_answers(claim.challenge, answers)
    claim.challenge.refresh_from_db()
    status = claim.challenge.status
    S = VerificationChallenge.Status
    if status == S.PASSED:
        claim.status = Claim.Status.VERIFIED
    elif status == S.REVIEW:
        claim.status = Claim.Status.REVIEW
    elif status == S.LOCKED:
        claim.status = Claim.Status.REJECTED
        claim.decision_note = "Verification failed – no attempts left."
        claim.decided_at = timezone.now()
    claim.save()
    audit(user, "claim.verification_attempt", claim, result=status, attempt=claim.challenge.attempts)
    _reopen_item_if_no_claims(claim.item)
    return attempt


@transaction.atomic
def review_verification(claim, reviewer, approve: bool, note=""):
    """Security decides a borderline (REVIEW) verification, or in-person check if no challenge."""
    if not is_security(reviewer):
        raise PermissionDenied
    if claim.status != Claim.Status.REVIEW:
        raise ValidationError("This claim is not under review.")
    challenge = getattr(claim, "challenge", None)
    if challenge is None:
        # Item had no hidden details: record in-person verification as a challenge result.
        challenge = VerificationChallenge.objects.create(claim=claim, detail_ids=[], status=VerificationChallenge.Status.REVIEW)
    vault.security_decision(challenge, reviewer, approve)
    claim.status = Claim.Status.VERIFIED if approve else Claim.Status.REJECTED
    if not approve:
        claim.decided_by, claim.decided_at, claim.decision_note = reviewer, timezone.now(), note or "Verification rejected by security."
    claim.save()
    audit(reviewer, "claim.verification_reviewed", claim, approved=approve)
    if not approve:
        notify(claim.claimant, Notification.Kind.CLAIM_DECIDED, f"Your claim on “{claim.item.title}” was not accepted.",
               url=claim.get_absolute_url())
        _reopen_item_if_no_claims(claim.item)
    return claim


@transaction.atomic
def approve_claim(claim, reviewer, note=""):
    if not is_security(reviewer):
        raise PermissionDenied("Only security personnel can approve claims.")
    item = Item.objects.select_for_update().get(pk=claim.item_id)   # serialise competing approvals
    claim = Claim.objects.select_for_update().get(pk=claim.pk)
    if claim.status != Claim.Status.VERIFIED or not claim.verification_passed:
        raise ValidationError("A claim can only be approved after the verification challenge has been passed.")
    if Claim.objects.filter(item=item, status__in=[Claim.Status.APPROVED, Claim.Status.HANDED_OVER]).exists():
        raise ValidationError("Another claim on this item has already been approved.")

    now = timezone.now()
    claim.status, claim.decided_by, claim.decided_at, claim.decision_note = Claim.Status.APPROVED, reviewer, now, note
    claim.save()
    item.status = Item.Status.CLAIM_APPROVED
    item.save(update_fields=["status", "updated_at"])

    competitors = Claim.objects.filter(item=item, status__in=Claim.OPEN_STATES).exclude(pk=claim.pk)
    for other in competitors:
        other.status, other.decided_by, other.decided_at = Claim.Status.REJECTED, reviewer, now
        other.decision_note = "Another claimant was verified as the owner."
        other.save()
        notify(other.claimant, Notification.Kind.CLAIM_DECIDED,
               f"Your claim on “{item.title}” was closed: another claimant was verified as the owner.",
               url=other.get_absolute_url())

    audit(reviewer, "claim.approved", claim, item=item.pk, competitors_rejected=len(competitors))
    notify(claim.claimant, Notification.Kind.CLAIM_DECIDED,
           f"Your claim on “{item.title}” is approved. Security will schedule the handover.", url=claim.get_absolute_url())
    return claim


@transaction.atomic
def reject_claim(claim, reviewer, note=""):
    if not is_security(reviewer):
        raise PermissionDenied
    if not claim.is_open:
        raise ValidationError("This claim is already closed.")
    claim.status, claim.decided_by, claim.decided_at = Claim.Status.REJECTED, reviewer, timezone.now()
    claim.decision_note = note or "Rejected by security."
    claim.save()
    audit(reviewer, "claim.rejected", claim)
    notify(claim.claimant, Notification.Kind.CLAIM_DECIDED, f"Your claim on “{claim.item.title}” was rejected.",
           url=claim.get_absolute_url())
    _reopen_item_if_no_claims(claim.item)
    return claim


@transaction.atomic
def withdraw_claim(claim, user):
    if claim.claimant_id != user.pk:
        raise PermissionDenied
    if claim.status not in (Claim.Status.VERIFYING, Claim.Status.REVIEW, Claim.Status.VERIFIED):
        raise ValidationError("This claim can no longer be withdrawn.")
    claim.status = Claim.Status.WITHDRAWN
    claim.save()
    audit(user, "claim.withdrawn", claim)
    _reopen_item_if_no_claims(claim.item)


def _reopen_item_if_no_claims(item):
    item.refresh_from_db()
    if item.status == Item.Status.CLAIM_PENDING and not item.claims.filter(status__in=Claim.OPEN_STATES).exists():
        has_custody = item.custody_records.exists()
        item.status = Item.Status.IN_CUSTODY if has_custody else Item.Status.OPEN
        item.save(update_fields=["status", "updated_at"])
