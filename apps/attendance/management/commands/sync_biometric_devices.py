from django.core.management.base import BaseCommand
from apps.attendance.biometrics import pull_all_active_devices


class Command(BaseCommand):
    help = (
        "Polls all active biometric devices configured for pull/both mode via "
        "HikVision ISAPI and ingests new attendance events. "
        "Intended to be run on a schedule, e.g. via cron every minute: "
        "* * * * * cd /path/to/project && /path/to/venv/bin/python manage.py sync_biometric_devices"
    )

    def handle(self, *args, **options):
        count = pull_all_active_devices()
        self.stdout.write(self.style.SUCCESS(f"Synced {count} biometric event(s) across all active devices."))
