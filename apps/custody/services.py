"""
Custody (M6) and disposal (M7).

* Intake: security records that a found item is now at a custody point.
* Handover: requires the Security role, an APPROVED claim whose verification
  PASSED, a valid OTP or a signature, and a proof photo.
* Disposal: only items in the disposal queue (past retention) can be disposed.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.roles import is_security
from apps.audit.models import Notification
from apps.audit.services import audit, notify, send_sms
from apps.claims.models import Claim
from apps.items.imaging import sanitize_image
from apps.items.models import Item

from .models import CustodyRecord, DisposalRecord, Handover

CFG = settings.LOSTFOUND


def _require_security(user):
    if not is_security(user):
        raise PermissionDenied("This action requires the Security role.")


def _hash_otp(otp: str) -> str:
    return hashlib.sha256((settings.SECRET_KEY + ":otp:" + otp).encode()).hexdigest()


@transaction.atomic
def record_intake(item, actor, location, from_party="", note=""):
    _require_security(actor)
    item = Item.objects.select_for_update().get(pk=item.pk)
    if not item.is_found:
        raise ValidationError("Only found items can be taken into custody.")
    if item.status in Item.CLOSED_STATES:
        raise ValidationError("This item is closed.")
    if not location.is_custody_point:
        raise ValidationError("Choose a security custody point.")
    action = CustodyRecord.Action.TRANSFER if item.custody_records.exists() else CustodyRecord.Action.INTAKE
    rec = CustodyRecord.objects.create(
        item=item, action=action, location=location, actor=actor,
        from_party=from_party or str(item.reporter), to_party=f"{actor} @ {location.name}", note=note,
    )
    if item.status == Item.Status.OPEN:
        item.status = Item.Status.IN_CUSTODY
        item.save(update_fields=["status", "updated_at"])
    audit(actor, f"custody.{action}", item, location=location.pk, record=rec.pk)
    return rec


def current_custody_location(item):
    rec = item.custody_records.exclude(action__in=["handover", "disposal"]).order_by("-created_at", "-pk").first()
    return rec.location if rec else None


@transaction.atomic
def schedule_handover(claim, actor, scheduled_for, location):
    """Create a handover and send the claimant a one-time code. Returns (handover, otp)."""
    _require_security(actor)
    claim = Claim.objects.select_for_update().get(pk=claim.pk)
    if claim.status != Claim.Status.APPROVED or not claim.verification_passed:
        raise ValidationError("Handover can only be scheduled for an approved, verified claim.")
    if not location.is_custody_point:
        raise ValidationError("Handover must take place at a security custody point.")
    if hasattr(claim, "handover") and claim.handover.status == Handover.Status.SCHEDULED:
        raise ValidationError("A handover is already scheduled for this claim.")

    otp = f"{secrets.randbelow(10**6):06d}"
    handover, _ = Handover.objects.update_or_create(
        claim=claim,
        defaults=dict(
            item=claim.item, status=Handover.Status.SCHEDULED, scheduled_for=scheduled_for, location=location,
            scheduled_by=actor, otp_hash=_hash_otp(otp), otp_attempts=0,
            otp_expires_at=timezone.now() + timedelta(minutes=CFG["OTP_TTL_MINUTES"]),
        ),
    )
    when = timezone.localtime(scheduled_for).strftime("%d %b %Y, %I:%M %p")
    notify(claim.claimant, Notification.Kind.HANDOVER_SCHEDULED,
           f"Collect “{claim.item.title}” at {location.name} on {when}. Bring your ID. Your handover code is {otp}.",
           url=claim.get_absolute_url())
    if claim.claimant.phone:
        send_sms(claim.claimant.phone, f"Lost&Found handover code: {otp}")
    audit(actor, "handover.scheduled", handover, claim=claim.pk)
    return handover, otp


def _check_otp(handover, actor, otp):
    """Validate the OTP. A wrong code is counted even though we then raise."""
    handover.refresh_from_db()
    if handover.otp_attempts >= CFG["OTP_MAX_ATTEMPTS"]:
        raise ValidationError("Too many wrong codes. Cancel and reschedule the handover.")
    if handover.otp_expires_at and handover.otp_expires_at < timezone.now():
        raise ValidationError("The handover code has expired. Reschedule to send a new one.")
    if not hmac.compare_digest(_hash_otp(otp.strip()), handover.otp_hash):
        Handover.objects.filter(pk=handover.pk).update(otp_attempts=F("otp_attempts") + 1)
        audit(actor, "handover.otp_failed", handover)
        raise ValidationError("Incorrect handover code.")


def complete_handover(handover, actor, *, proof_photo, otp="", signature_file=None, id_checked=""):
    """The supervised handover itself. Every precondition is checked here."""
    _require_security(actor)
    if not proof_photo:
        raise ValidationError("A proof photo of the handover is required.")
    if otp:
        _check_otp(handover, actor, otp)
        method = Handover.Method.OTP
    elif signature_file:
        method = Handover.Method.SIGNATURE
    else:
        raise ValidationError("Enter the claimant's one-time code or capture their signature.")
    with transaction.atomic():
        return _complete(handover, actor, method, proof_photo, signature_file, id_checked)


def _complete(handover, actor, method, proof_photo, signature_file, id_checked):
    handover = Handover.objects.select_for_update().get(pk=handover.pk)
    claim = Claim.objects.select_for_update().get(pk=handover.claim_id)
    item = Item.objects.select_for_update().get(pk=handover.item_id)
    if handover.status != Handover.Status.SCHEDULED:
        raise ValidationError("This handover is not open.")
    if claim.status != Claim.Status.APPROVED or not claim.verification_passed:
        raise ValidationError("The claim must be approved and verified before handover.")

    full, _thumb = sanitize_image(proof_photo)
    handover.proof_photo.save(full.name, full, save=False)
    if signature_file:
        handover.signature.save(f"sig_{handover.pk}.png", signature_file, save=False)
    handover.method = method
    handover.id_checked = id_checked[:80]
    handover.supervised_by = actor
    handover.completed_at = timezone.now()
    handover.status = Handover.Status.COMPLETED
    handover.otp_hash = ""
    handover.save()

    CustodyRecord.objects.create(
        item=item, action=CustodyRecord.Action.HANDOVER, location=handover.location, actor=actor,
        from_party=f"{actor} @ {handover.location.name}", to_party=str(claim.claimant),
        note=f"Verified by {handover.get_method_display()}; handover #{handover.pk}",
    )
    claim.status = Claim.Status.HANDED_OVER
    claim.save()
    item.status = Item.Status.RETURNED
    item.save(update_fields=["status", "updated_at"])
    if claim.lost_report_id:
        Item.objects.filter(pk=claim.lost_report_id).update(status=Item.Status.RESOLVED)

    audit(actor, "handover.completed", handover, method=method, claim=claim.pk)
    notify(claim.claimant, Notification.Kind.HANDOVER_DONE, f"“{item.title}” has been handed over to you. Case closed.",
           url=claim.get_absolute_url())
    notify(item.reporter, Notification.Kind.HANDOVER_DONE,
           f"The item you found (“{item.title}”) was returned to its owner. Thank you!", url=item.get_absolute_url(), email=False)
    return handover


def cancel_handover(handover, actor):
    _require_security(actor)
    if handover.status != Handover.Status.SCHEDULED:
        raise ValidationError("Only scheduled handovers can be cancelled.")
    handover.status = Handover.Status.CANCELLED
    handover.otp_hash = ""
    handover.save()
    audit(actor, "handover.cancelled", handover)


# --- Ageing & disposal (M7) ---------------------------------------------------

AGEABLE = [Item.Status.OPEN, Item.Status.IN_CUSTODY, Item.Status.AGEING]


def age_items(now=None):
    """
    Move unclaimed found items through: (in custody) -> ageing -> disposal queue,
    based on each category's retention_days. Items with an open claim are skipped.
    Returns dict of counts. Run nightly: `python manage.py run_nightly`.
    """
    from apps.accounts.models import User
    from apps.accounts.roles import SECURITY

    now = now or timezone.now()
    warn_days = CFG["AGEING_WARNING_DAYS"]
    counts = {"warned": 0, "queued": 0}
    security_users = list(User.objects.filter(groups__name=SECURITY, is_active=True))
    qs = Item.objects.filter(kind=Item.Kind.FOUND, status__in=AGEABLE).select_related("category")
    for item in qs:
        if item.claims.filter(status__in=Claim.OPEN_STATES).exists():
            continue
        age = (now - item.custody_started_at()).days
        retention = item.category.retention_days
        if age >= retention:
            item.status = Item.Status.DISPOSAL_QUEUE
            item.save(update_fields=["status", "updated_at"])
            audit(None, "item.disposal_queued", item, age_days=age)
            counts["queued"] += 1
        elif age >= retention - warn_days and item.status != Item.Status.AGEING:
            item.status = Item.Status.AGEING
            item.ageing_warned_at = now
            item.save(update_fields=["status", "ageing_warned_at", "updated_at"])
            audit(None, "item.ageing_warning", item, age_days=age)
            for u in security_users:
                notify(u, Notification.Kind.AGEING_WARNING,
                       f"“{item.title}” will reach its retention limit in {retention - age} day(s).",
                       url=f"/desk/item/{item.pk}/", email=False)
            counts["warned"] += 1
    return counts


@transaction.atomic
def dispose(item, actor, method, recipient="", note="", proof_photo=None):
    _require_security(actor)
    item = Item.objects.select_for_update().get(pk=item.pk)
    if item.status != Item.Status.DISPOSAL_QUEUE:
        raise ValidationError("Only items in the disposal queue can be disposed.")
    record = DisposalRecord(item=item, method=method, recipient=recipient, note=note, approved_by=actor)
    if proof_photo:
        full, _ = sanitize_image(proof_photo)
        record.proof_photo.save(full.name, full, save=False)
    record.save()
    CustodyRecord.objects.create(
        item=item, action=CustodyRecord.Action.DISPOSAL, location=current_custody_location(item), actor=actor,
        from_party=str(actor), to_party=recipient or record.get_method_display(), note=note,
    )
    item.status = Item.Status.DISPOSED
    item.save(update_fields=["status", "updated_at"])
    audit(actor, "item.disposed", item, method=method)
    return record
