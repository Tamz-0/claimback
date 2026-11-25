from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.roles import is_security
from apps.board.public import to_public
from apps.items.models import Item
from apps.vault import services as vault

from . import services
from .models import Claim


class ClaimForm(forms.Form):
    statement = forms.CharField(
        required=False, label="Anything that helps (optional)",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Where and when you think you lost it"}),
    )
    lost_report = forms.ModelChoiceField(queryset=Item.objects.none(), required=False, label="Link to your lost report")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lost_report"].queryset = Item.objects.filter(
            reporter=user, kind=Item.Kind.LOST, status__in=Item.ACTIVE_STATES
        )


@login_required
def claim_item(request, item_pk):
    item = get_object_or_404(Item.objects.select_related("category", "location"), pk=item_pk, kind=Item.Kind.FOUND)
    form = ClaimForm(request.POST or None, user=request.user,
                     initial={"lost_report": request.GET.get("lost")})
    if request.method == "POST" and form.is_valid():
        try:
            claim = services.submit_claim(item=item, claimant=request.user,
                                          statement=form.cleaned_data["statement"],
                                          lost_report=form.cleaned_data["lost_report"])
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("board:detail", pk=item.pk)
        return redirect(claim.get_absolute_url())
    return render(request, "claims/claim_form.html", {"item": to_public(item), "form": form})


@login_required
def claim_detail(request, pk):
    claim = get_object_or_404(Claim.objects.select_related("item__category", "item__location"), pk=pk)
    if claim.claimant_id != request.user.pk:
        if is_security(request.user):
            return redirect("dashboard:desk_claim", pk=pk)
        raise PermissionDenied

    challenge = getattr(claim, "challenge", None)
    questions = []
    if claim.status == Claim.Status.VERIFYING and challenge and challenge.can_answer:
        questions = vault.challenge_questions(challenge)  # questions only

    if request.method == "POST" and questions:
        answers = {str(pk): request.POST.get(f"answer_{pk}", "") for pk, _q in questions}
        if not any(a.strip() for a in answers.values()):
            messages.error(request, "Please answer the questions.")
        else:
            try:
                services.answer_challenge(claim, request.user, answers)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            return redirect(claim.get_absolute_url())

    handover = getattr(claim, "handover", None)
    return render(request, "claims/detail.html", {
        "claim": claim, "item": to_public(claim.item), "challenge": challenge,
        "questions": questions, "handover": handover,
    })


@login_required
@require_POST
def withdraw(request, pk):
    claim = get_object_or_404(Claim, pk=pk)
    try:
        services.withdraw_claim(claim, request.user)
        messages.success(request, "Claim withdrawn.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect(claim.get_absolute_url())
