from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Location
from apps.claims import services as claims
from apps.custody import services as custody
from apps.items.models import Item
from apps.matching.engine import refresh_all

from ... import demo_data as D
from ... import seeding


class Command(BaseCommand):
    help = "Load categories, campus locations, demo users (one per role) and sample items."

    def add_arguments(self, parser):
        parser.add_argument("--reference-only", action="store_true", help="Only categories, locations and role groups")

    @transaction.atomic
    def handle(self, *args, **opts):
        seeding.seed_reference_data()
        self.stdout.write(self.style.SUCCESS("✓ Categories, campus locations and role groups"))
        if opts["reference_only"]:
            return
        if Item.objects.exists():
            self.stdout.write(self.style.WARNING("Items already exist – skipping sample items."))
            return

        users = seeding.seed_users()
        self.stdout.write(self.style.SUCCESS(f"✓ Users (password for all: {D.DEMO_PASSWORD})"))

        pairs = seeding.seed_match_pairs(users["student1"], users["student2"], pairs=D.MATCH_PAIRS[:12])
        seeding.seed_distractors(users["staff1"])
        security = users["security1"]
        desk = Location.objects.get(name="Security Office", parent__name="Main Gate")
        library_desk = Location.objects.get(name="Library Security Desk")

        # Most found items have been handed in to security
        for i, (_lost, found) in enumerate(pairs):
            if i % 4 != 3:
                custody.record_intake(found, security, library_desk if i % 2 else desk)

        # One complete story: claim -> verify -> approve -> handover scheduled
        lost, found = pairs[0]
        claim = claims.submit_claim(item=found, claimant=users["student1"], lost_report=lost,
                                    statement="Lost it after the DBMS lecture.")
        answers = {
            "What is the lock-screen wallpaper?": "a golden retriever puppy",
            "Describe the phone case.": "transparent case with dried flower",
            "Any cracks or scratches? Where?": "crack in top left corner",
        }
        from apps.vault.services import challenge_questions

        claims.answer_challenge(claim, users["student1"],
                                {str(pk): answers.get(q, "") for pk, q in challenge_questions(claim.challenge)})
        claim.refresh_from_db()
        if claim.status == claim.Status.VERIFIED:
            claims.approve_claim(claim, security, "Verified at desk")
            custody.schedule_handover(claim, security, timezone.now() + timedelta(hours=3), desk)

        # A competing / failed claim on another item
        _lost2, found2 = pairs[1]
        bad = claims.submit_claim(item=found2, claimant=users["student3"], statement="I think it's mine")
        claims.answer_challenge(bad, users["student3"], {str(pk): "no idea" for pk in bad.challenge.detail_ids})

        # An old unclaimed item for the ageing/disposal demo
        old = Item.objects.filter(kind=Item.Kind.FOUND, title="Umbrella").first()
        if old:
            from apps.custody.models import CustodyRecord

            long_ago = timezone.now() - timedelta(days=40)
            CustodyRecord.objects.create(item=old, action=CustodyRecord.Action.INTAKE, location=desk, actor=security,
                                         from_party="staff1", to_party=f"{security} @ {desk.name}", created_at=long_ago)
            Item.objects.filter(pk=old.pk).update(status=Item.Status.IN_CUSTODY, created_at=long_ago, occurred_at=long_ago)

        n = refresh_all()
        counts = custody.age_items()
        self.stdout.write(self.style.SUCCESS(f"✓ Sample items, {n} match suggestions, ageing: {counts}"))
        self.stdout.write("\nLog in as: " + ", ".join(u for u, *_ in D.USERS))
