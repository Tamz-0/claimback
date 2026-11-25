import base64
import binascii
import csv
from datetime import date, datetime, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.roles import is_campus_admin, is_security, is_staff_role, role_required
from apps.catalog.models import Location
from apps.claims import services as claim_services
from apps.claims.models import Claim
from apps.custody import services as custody
from apps.custody.models import CustodyRecord, DisposalRecord, Handover, verify_chain
from apps.items.models import Item
from apps.matching.models import MatchSuggestion
from apps.vault import services as vault

from . import analytics


def _errors(request, exc):
    messages.error(request, " ".join(getattr(exc, "messages", [str(exc)])))


# --- Student / staff home ----------------------------------------------------

@login_required
def home(request):
    if is_security(request.user) and not request.GET.get("mine"):
        return redirect("dashboard:desk")
    reports = (Item.objects.filter(reporter=request.user).select_related("category", "location")
               .annotate(match_count=Count("matches_as_lost", filter=~Q(matches_as_lost__status="dismissed"))))
    claims = Claim.objects.filter(claimant=request.user).select_related("item")
    return render(request, "dashboard/home.html", {"reports": reports, "claims": claims})


# --- Security desk -------------------------------------------------------------

@role_required(is_security)
def desk(request):
    found = Item.objects.filter(kind=Item.Kind.FOUND).select_related("category", "location")
    inventory = []
    for loc in Location.objects.filter(is_custody_point=True):
        ids = [i.pk for i in found.filter(status__in=[Item.Status.IN_CUSTODY, Item.Status.CLAIM_PENDING,
                                                       Item.Status.CLAIM_APPROVED, Item.Status.AGEING,
                                                       Item.Status.DISPOSAL_QUEUE])
               if custody.current_custody_location(i) == loc]
        inventory.append((loc, len(ids)))
    ctx = {
        "intake": found.filter(status=Item.Status.OPEN)[:50],
        "review": Claim.objects.filter(status=Claim.Status.REVIEW).select_related("item", "claimant"),
        "verified": Claim.objects.filter(status=Claim.Status.VERIFIED).select_related("item", "claimant"),
        "approved": Claim.objects.filter(status=Claim.Status.APPROVED).select_related("item", "claimant")
                    .exclude(handover__status=Handover.Status.SCHEDULED),
        "handovers": Handover.objects.filter(status=Handover.Status.SCHEDULED).select_related("item", "claim__claimant", "location"),
        "ageing": found.filter(status=Item.Status.AGEING),
        "disposal": found.filter(status=Item.Status.DISPOSAL_QUEUE),
        "inventory": inventory,
        "custody_points": Location.objects.filter(is_custody_point=True),
    }
    ctx["action_count"] = len(ctx["review"]) + len(ctx["verified"]) + len(ctx["approved"])
    return render(request, "dashboard/desk.html", ctx)


class IntakeForm(forms.Form):
    location = forms.ModelChoiceField(queryset=Location.objects.filter(is_custody_point=True), label="Custody point")
    from_party = forms.CharField(required=False, max_length=120, label="Handed in by")
    note = forms.CharField(required=False, max_length=300)


class DisposalForm(forms.Form):
    method = forms.ChoiceField(choices=DisposalRecord.Method.choices)
    recipient = forms.CharField(required=False, max_length=120)
    note = forms.CharField(required=False, max_length=300)


@role_required(is_security)
def desk_item(request, pk):
    item = get_object_or_404(Item.objects.select_related("category", "location", "reporter"), pk=pk)
    intake_form = IntakeForm(request.POST if "intake" in request.POST else None, initial={"from_party": str(item.reporter)})
    disposal_form = DisposalForm(request.POST if "dispose" in request.POST else None)
    if request.method == "POST":
        try:
            if "intake" in request.POST and intake_form.is_valid():
                custody.record_intake(item, request.user, **intake_form.cleaned_data)
                messages.success(request, "Custody recorded.")
                return redirect("dashboard:desk_item", pk=pk)
            if "dispose" in request.POST and disposal_form.is_valid():
                custody.dispose(item, request.user, proof_photo=request.FILES.get("proof_photo"), **disposal_form.cleaned_data)
                messages.success(request, "Disposal recorded.")
                return redirect("dashboard:desk_item", pk=pk)
        except ValidationError as exc:
            _errors(request, exc)
    chain_ok, bad = verify_chain(item)
    return render(request, "dashboard/desk_item.html", {
        "item": item,
        "private_details": vault.details_for_owner_view(item, request.user) if item.is_found else [],
        "claims": item.claims.select_related("claimant", "challenge"),
        "custody": item.custody_records.select_related("location", "actor"),
        "chain_ok": chain_ok, "chain_bad": bad,
        "current_location": custody.current_custody_location(item),
        "intake_form": intake_form, "disposal_form": disposal_form,
    })


class ScheduleForm(forms.Form):
    scheduled_for = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
                                        input_formats=["%Y-%m-%dT%H:%M"])
    location = forms.ModelChoiceField(queryset=Location.objects.filter(is_custody_point=True))


@role_required(is_security)
def desk_claim(request, pk):
    claim = get_object_or_404(Claim.objects.select_related("item", "claimant", "lost_report"), pk=pk)
    challenge = getattr(claim, "challenge", None)
    default_loc = custody.current_custody_location(claim.item)
    schedule_form = ScheduleForm(
        request.POST if request.POST.get("action") == "schedule" else None,
        initial={"scheduled_for": (timezone.localtime() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
                 "location": default_loc.pk if default_loc else None},
    )
    if request.method == "POST":
        action, note = request.POST.get("action"), request.POST.get("note", "")[:300]
        try:
            if action == "review_pass":
                claim_services.review_verification(claim, request.user, True, note)
            elif action == "review_fail":
                claim_services.review_verification(claim, request.user, False, note)
            elif action == "approve":
                claim_services.approve_claim(claim, request.user, note)
            elif action == "reject":
                claim_services.reject_claim(claim, request.user, note)
            elif action == "schedule":
                if not schedule_form.is_valid():
                    raise ValidationError("Check the handover time and place.")
                custody.schedule_handover(claim, request.user, **schedule_form.cleaned_data)
                messages.success(request, "Handover scheduled. The claimant has been sent a one-time code.")
            else:
                raise ValidationError("Unknown action.")
            if action != "schedule":
                messages.success(request, "Saved.")
            return redirect("dashboard:desk_claim", pk=pk)
        except ValidationError as exc:
            _errors(request, exc)
    competing = claim.item.claims.exclude(pk=claim.pk).select_related("claimant")
    return render(request, "dashboard/desk_claim.html", {
        "claim": claim, "challenge": challenge,
        "attempts": vault.review_data(challenge, request.user) if challenge else [],
        "competing": competing, "schedule_form": schedule_form,
        "handover": getattr(claim, "handover", None),
    })


def _signature_file(data_url):
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) < 200 or len(raw) > 2_000_000:   # blank canvas or absurd size
        return None
    return ContentFile(raw, name="signature.png")


@role_required(is_security)
def desk_handover(request, pk):
    handover = get_object_or_404(Handover.objects.select_related("item", "claim__claimant", "location"), pk=pk)
    if request.method == "POST":
        try:
            if request.POST.get("action") == "cancel":
                custody.cancel_handover(handover, request.user)
                messages.info(request, "Handover cancelled. You can schedule a new one from the claim page.")
                return redirect("dashboard:desk_claim", pk=handover.claim_id)
            custody.complete_handover(
                handover, request.user,
                proof_photo=request.FILES.get("proof_photo"),
                otp=request.POST.get("otp", "").strip(),
                signature_file=_signature_file(request.POST.get("signature", "")),
                id_checked=request.POST.get("id_checked", ""),
            )
            messages.success(request, "Handover complete. Custody chain updated.")
            return redirect("dashboard:desk_item", pk=handover.item_id)
        except ValidationError as exc:
            _errors(request, exc)
            handover.refresh_from_db()
    return render(request, "dashboard/desk_handover.html", {"handover": handover})


@role_required(is_security)
def desk_matches(request):
    matches = (MatchSuggestion.objects.filter(status=MatchSuggestion.Status.SUGGESTED,
                                               lost__status__in=Item.ACTIVE_STATES, found__status__in=Item.ACTIVE_STATES)
               .select_related("lost__category", "found__category", "lost__location", "found__location")[:100])
    return render(request, "dashboard/desk_matches.html", {"matches": matches})


@role_required(is_security)
@require_POST
def desk_match_action(request, pk):
    match = get_object_or_404(MatchSuggestion, pk=pk)
    action = request.POST.get("action")
    if action == "confirm":
        match.status = MatchSuggestion.Status.CONFIRMED
        from apps.audit.models import Notification
        from apps.audit.services import notify

        notify(match.lost.reporter, Notification.Kind.MATCH_FOUND,
               f"Security thinks “{match.found.title}” is your lost item. Open it and submit a claim.",
               url=match.lost.get_absolute_url())
    elif action == "dismiss":
        match.status = MatchSuggestion.Status.DISMISSED
    match.save(update_fields=["status"])
    return redirect("dashboard:desk_matches")


@role_required(is_security)
def desk_audit(request):
    from apps.audit.models import AuditEntry

    return render(request, "dashboard/desk_audit.html", {"entries": AuditEntry.objects.select_related("actor")[:200]})


# --- Reports -----------------------------------------------------------------

def _parse(d):
    try:
        return date.fromisoformat(d) if d else None
    except ValueError:
        return None


@role_required(is_staff_role)
def reports(request):
    start, end = _parse(request.GET.get("from")), _parse(request.GET.get("to"))
    data = analytics.summary(start, end)
    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="lost-found-report.csv"'
        w = csv.writer(resp)
        w.writerow(["metric", "value"])
        for key in ("found_total", "lost_total", "returned", "return_rate", "lost_resolved", "median_hours_to_return",
                    "verification_attempts", "verification_failed", "verification_failure_rate", "unclaimed", "disposed"):
            w.writerow([key, data[key]])
        w.writerow([])
        w.writerow(["hotspot_building", "lost_count"])
        w.writerows(data["hotspots"])
        w.writerow([])
        w.writerow(["category", "count"])
        w.writerows([(c["name"], c["n"]) for c in data["categories"]])
        return resp
    max_hour = max([n for _h, n in data["by_hour"]] + [1])
    max_hot = max([n for _b, n in data["hotspots"]] + [1])
    max_cat = max([c["n"] for c in data["categories"]] + [1])
    return render(request, "dashboard/reports.html", {
        "d": data, "max_hour": max_hour, "max_hot": max_hot, "max_cat": max_cat,
        "start": request.GET.get("from", ""), "end": request.GET.get("to", ""),
    })
