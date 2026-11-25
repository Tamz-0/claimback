from django.core.management.base import BaseCommand

from apps.custody.services import age_items
from apps.matching.engine import refresh_all


class Command(BaseCommand):
    help = "Nightly jobs: refresh match suggestions and age unclaimed items. Schedule with cron / Task Scheduler."

    def handle(self, *args, **opts):
        n = refresh_all()
        counts = age_items()
        self.stdout.write(self.style.SUCCESS(f"Matches refreshed: {n}. Ageing: {counts}"))
