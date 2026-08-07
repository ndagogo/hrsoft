from django.core.management.base import BaseCommand

from apps.attendance.models import BiometricDevice


class Command(BaseCommand):
    help = "Align Main Gate Terminal with ZKTeco Ethernet settings (192.168.1.201:4370)."

    def handle(self, *args, **options):
        device, created = BiometricDevice.objects.update_or_create(
            name="Main Gate Terminal",
            defaults={
                "brand": "zkteco",
                "connection_mode": "pull",
                "ip_address": "192.168.1.201",
                "port": 4370,
                "comm_key": 0,
                "username": "",
                "password": "",
                "location": "Main Building - Ground Floor Entrance",
                "is_active": True,
                "last_sync_status": "never",
                "last_sync_message": "Configured for ZKTeco TCP 4370 (static IP, DHCP Off).",
            },
        )
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} {device.name} -> {device.brand} {device.ip_address}:{device.port}"
        ))
