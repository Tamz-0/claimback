"""
API serializers.

* PublicItemSerializer delegates entirely to board.public.to_public(): the
  public JSON is the same allow-listed DTO as the public HTML board.
* ItemSerializer (authenticated) has `private_details` as WRITE-ONLY: it can be
  submitted when reporting a found item but is never part of any response.
"""

from rest_framework import serializers

from apps.board.public import PUBLIC_FIELDS, to_public
from apps.catalog.models import Category, Location
from apps.claims.models import Claim
from apps.custody.models import Handover
from apps.items.models import Item
from apps.matching.models import MatchSuggestion


class PublicItemSerializer(serializers.BaseSerializer):
    """Read-only. Output is exactly board.public.to_public(item)."""

    def to_representation(self, instance):
        data = to_public(instance)
        request = self.context.get("request")
        if request:
            for key in ("photo", "thumbnail"):
                if data[key]:
                    data[key] = request.build_absolute_uri(data[key])
        return data


PublicItemSerializer.public_fields = PUBLIC_FIELDS


class PrivateDetailInput(serializers.Serializer):
    question = serializers.CharField(max_length=300)
    answer = serializers.CharField(max_length=300)


class ItemSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(slug_field="slug", queryset=Category.objects.filter(is_active=True))
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.filter(is_active=True))
    private_details = PrivateDetailInput(many=True, write_only=True, required=False)
    location_name = serializers.CharField(source="location.full_name", read_only=True)
    photos = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = ("id", "kind", "status", "title", "description", "category", "attributes", "location",
                  "location_name", "occurred_at", "photo_public", "photos", "created_at", "private_details")
        read_only_fields = ("status", "created_at")

    def get_photos(self, obj):
        request = self.context.get("request")
        return [request.build_absolute_uri(p.thumbnail.url) if request else p.thumbnail.url for p in obj.photos.all()]


class MatchSerializer(serializers.ModelSerializer):
    lost = PublicItemSerializer(read_only=True)
    found = PublicItemSerializer(read_only=True)

    class Meta:
        model = MatchSuggestion
        fields = ("id", "score", "breakdown", "status", "lost", "found")


class ClaimSerializer(serializers.ModelSerializer):
    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.filter(kind=Item.Kind.FOUND))
    verification = serializers.SerializerMethodField()

    class Meta:
        model = Claim
        fields = ("id", "item", "lost_report", "statement", "status", "decision_note", "created_at", "verification")
        read_only_fields = ("status", "decision_note", "created_at")

    def get_verification(self, obj):
        from apps.vault.services import challenge_questions

        ch = getattr(obj, "challenge", None)
        if ch is None:
            return None
        out = {"status": ch.status, "attempts_left": ch.attempts_left, "questions": []}
        request = self.context.get("request")
        # Questions only — and only to the claimant while the challenge is open
        if request and request.user.pk == obj.claimant_id and obj.status == Claim.Status.VERIFYING and ch.can_answer:
            out["questions"] = [{"id": pk, "question": q} for pk, q in challenge_questions(ch)]
        return out


class VerifySerializer(serializers.Serializer):
    answers = serializers.DictField(child=serializers.CharField(max_length=300, allow_blank=True))


class HandoverSerializer(serializers.ModelSerializer):
    class Meta:
        model = Handover
        fields = ("id", "claim", "item", "status", "scheduled_for", "location", "method", "completed_at")
        read_only_fields = ("item", "status", "method", "completed_at")
