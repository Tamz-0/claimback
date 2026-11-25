"""
REST API (spec section 8):

    GET/POST  /api/items/                 own reports (security: all)
    GET       /api/items/{id}/
    GET       /api/items/{id}/matches/
    GET/POST  /api/claims/
    GET       /api/claims/{id}/
    POST      /api/claims/{id}/verify/    {"answers": {"<question id>": "text"}}
    GET/POST  /api/handovers/             security only
    POST      /api/handovers/{id}/complete/   multipart: otp, proof_photo
    GET       /api/board/                 PUBLIC, redacted
"""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.roles import is_security
from apps.board.search import board_queryset
from apps.claims import services as claim_services
from apps.claims.models import Claim
from apps.custody import services as custody
from apps.custody.models import Handover
from apps.items import services as item_services
from apps.items.models import Item
from apps.matching.models import MatchSuggestion

from .serializers import (
    ClaimSerializer, HandoverSerializer, ItemSerializer, MatchSerializer, PublicItemSerializer, VerifySerializer,
)


def _django_to_drf(exc):
    if isinstance(exc, DjangoPermissionDenied):
        return PermissionDenied(str(exc) or None)
    return ValidationError({"detail": exc.messages if hasattr(exc, "messages") else [str(exc)]})


class IsSecurity(permissions.BasePermission):
    def has_permission(self, request, view):
        return is_security(request.user)


class BoardViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Public, redacted board. No authentication needed."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = PublicItemSerializer

    def get_queryset(self):
        return board_queryset(self.request.query_params)


class ItemViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ItemSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = Item.objects.select_related("category", "location").prefetch_related("photos")
        if is_security(self.request.user):
            return qs
        return qs.filter(reporter=self.request.user)

    def perform_create(self, serializer):
        data = serializer.validated_data
        try:
            item = item_services.create_report(
                reporter=self.request.user, kind=data["kind"], title=data["title"],
                description=data.get("description", ""), category=data["category"], location=data["location"],
                occurred_at=data.get("occurred_at") or timezone.now(),
                attributes=data.get("attributes") or {},
                photos=self.request.FILES.getlist("photos")[:4],
                private_pairs=[(d["question"], d["answer"]) for d in data.get("private_details", [])],
                photo_public=data.get("photo_public", True),
            )
        except DjangoValidationError as exc:
            raise _django_to_drf(exc)
        serializer.instance = item

    @action(detail=True)
    def matches(self, request, pk=None):
        item = self.get_object()
        qs = MatchSuggestion.objects.filter(Q(lost=item) | Q(found=item)).exclude(status="dismissed")
        if item.kind == Item.Kind.FOUND and not is_security(request.user):
            qs = qs.none()   # finders don't need to see who lost things
        return Response(MatchSerializer(qs.select_related("lost", "found"), many=True, context={"request": request}).data)


class ClaimViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ClaimSerializer

    def get_queryset(self):
        qs = Claim.objects.select_related("item", "challenge")
        if is_security(self.request.user):
            return qs
        return qs.filter(claimant=self.request.user)

    def perform_create(self, serializer):
        data = serializer.validated_data
        try:
            serializer.instance = claim_services.submit_claim(
                item=data["item"], claimant=self.request.user,
                statement=data.get("statement", ""), lost_report=data.get("lost_report"),
            )
        except DjangoValidationError as exc:
            raise _django_to_drf(exc)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        claim = self.get_object()
        body = VerifySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            attempt = claim_services.answer_challenge(claim, request.user, body.validated_data["answers"])
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            raise _django_to_drf(exc)
        claim.refresh_from_db()
        return Response({"claim_status": claim.status, "verification_status": claim.challenge.status,
                         "attempts_left": claim.challenge.attempts_left, "score": attempt.score})


class HandoverViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = HandoverSerializer
    permission_classes = [permissions.IsAuthenticated, IsSecurity]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    queryset = Handover.objects.select_related("claim", "item", "location")

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            handover, _otp = custody.schedule_handover(
                ser.validated_data["claim"], request.user, ser.validated_data["scheduled_for"], ser.validated_data["location"]
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            raise _django_to_drf(exc)
        # The OTP goes only to the claimant (notification), never in the API response.
        return Response(HandoverSerializer(handover).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        handover = self.get_object()
        try:
            custody.complete_handover(
                handover, request.user, proof_photo=request.FILES.get("proof_photo"),
                otp=request.data.get("otp", ""), id_checked=request.data.get("id_checked", ""),
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            raise _django_to_drf(exc)
        handover.refresh_from_db()
        return Response(HandoverSerializer(handover).data)
