import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.roles import is_security
from apps.board.public import to_public
from apps.catalog.models import Category, Location
from apps.claims.models import Claim
from apps.matching.models import MatchSuggestion
from apps.vault import services as vault

from . import services
from .forms import MAX_PRIVATE, ReportForm
from .models import Item


def _picker_context():
    cats = {
        str(c.pk): {"attributes": c.attributes, "prompts": c.verification_prompts}
        for c in Category.objects.filter(is_active=True)
    }
    locs = [
        {"id": l.pk, "name": l.name, "full": l.full_name, "parent": l.parent_id, "kind": l.kind, "x": l.map_x, "y": l.map_y}
        for l in Location.objects.filter(is_active=True).select_related("parent", "parent__parent")
    ]
    return {"category_data": cats, "location_data": locs}


@login_required
def report(request, kind):
    if kind not in (Item.Kind.LOST, Item.Kind.FOUND):
        raise Http404
    form = ReportForm(request.POST or None, kind=kind)
    if request.method == "POST" and form.is_valid():
        try:
            item = services.create_report(
                reporter=request.user, kind=kind,
                title=form.cleaned_data["title"], description=form.cleaned_data["description"],
                category=form.cleaned_data["category"], location=form.cleaned_data["location"],
                occurred_at=form.cleaned_data["occurred_at"],
                attributes=form.attributes_from(request.POST),
                photos=ReportForm.photos_from(request.FILES),
                private_pairs=ReportForm.private_pairs_from(request.POST) if kind == Item.Kind.FOUND else (),
                photo_public=form.cleaned_data["photo_public"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if kind == Item.Kind.FOUND:
                messages.success(request, "Thank you! Please hand the item in at the nearest security desk.")
            else:
                messages.success(request, "Lost report saved. We'll notify you when a possible match is found.")
            return redirect(item.get_absolute_url())
    ctx = {
        "form": form, "kind": kind,
        "private_rows": [(i, request.POST.get(f"pq_{i}", ""), request.POST.get(f"pa_{i}", "")) for i in range(1, MAX_PRIVATE + 1)],
        **_picker_context(),
    }
    return render(request, "items/report.html", ctx)


@login_required
def item_detail(request, pk):
    """Private view of a report: for its reporter and for security."""
    item = get_object_or_404(Item.objects.select_related("category", "location", "reporter"), pk=pk)
    security = is_security(request.user)
    if item.reporter_id != request.user.pk and not security:
        return redirect("board:detail", pk=pk)

    ctx = {"item": item, "public": to_public(item), "is_security_view": security}
    ctx["private_details"] = vault.details_for_owner_view(item, request.user) if item.is_found else []
    if item.kind == Item.Kind.LOST:
        matches = (MatchSuggestion.objects.filter(lost=item).exclude(status=MatchSuggestion.Status.DISMISSED)
                   .select_related("found__category", "found__location").prefetch_related("found__photos"))
        ctx["matches"] = [{"m": m, "item": to_public(m.found)} for m in matches if m.found.status in Item.ACTIVE_STATES]
        ctx["my_claims"] = Claim.objects.filter(lost_report=item).select_related("item")
    else:
        matches = MatchSuggestion.objects.filter(found=item).select_related("lost__category", "lost__location")
        ctx["matches"] = [{"m": m, "item": to_public(m.lost)} for m in matches] if security else []
        ctx["claims_summary"] = {
            "open": item.claims.filter(status__in=Claim.OPEN_STATES).count(),
            "total": item.claims.count(),
        }
    ctx["custody"] = item.custody_records.select_related("location", "actor")
    return render(request, "items/detail.html", ctx)


@login_required
@require_POST
def dismiss_match(request, pk):
    match = get_object_or_404(MatchSuggestion, pk=pk)
    if match.lost.reporter_id != request.user.pk and not is_security(request.user):
        raise PermissionDenied
    match.status = MatchSuggestion.Status.DISMISSED
    match.save(update_fields=["status"])
    messages.info(request, "Suggestion dismissed.")
    return redirect(match.lost.get_absolute_url())


@login_required
@require_POST
def withdraw(request, pk):
    item = get_object_or_404(Item, pk=pk)
    try:
        services.withdraw(item, request.user)
        messages.success(request, "Report closed.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect(item.get_absolute_url())
