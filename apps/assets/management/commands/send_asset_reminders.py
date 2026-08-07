from django.core.management.base import BaseCommand

from apps.assets.services import send_asset_reminders


class Command(BaseCommand):
    help = "Send asset warranty, maintenance, and overdue return reminders."

    def handle(self, *args, **options):
        send_asset_reminders()
        self.stdout.write(self.style.SUCCESS("Asset reminders processed."))
