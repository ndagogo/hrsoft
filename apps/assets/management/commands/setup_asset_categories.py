"""Seed enterprise asset categories for Health Focus Diagnostics."""

from django.core.management.base import BaseCommand

from apps.assets.models import AssetCategory, AssetCategoryGroup

CATEGORIES = [
    # IT
    ("laptop", "Laptop", AssetCategoryGroup.IT),
    ("desktop", "Desktop", AssetCategoryGroup.IT),
    ("tablet", "Tablet", AssetCategoryGroup.IT),
    ("phone", "Phone", AssetCategoryGroup.IT),
    ("printer", "Printer", AssetCategoryGroup.IT),
    ("scanner", "Scanner", AssetCategoryGroup.IT),
    ("server", "Server", AssetCategoryGroup.IT),
    ("router", "Router", AssetCategoryGroup.IT),
    ("switch", "Network Switch", AssetCategoryGroup.IT),
    ("ups", "UPS", AssetCategoryGroup.IT),
    ("projector", "Projector", AssetCategoryGroup.IT),
    ("monitor", "Workstation Monitor", AssetCategoryGroup.IT),
    # Office
    ("chair", "Chair", AssetCategoryGroup.OFFICE),
    ("table", "Table", AssetCategoryGroup.OFFICE),
    ("cabinet", "Cabinet", AssetCategoryGroup.OFFICE),
    ("whiteboard", "Whiteboard", AssetCategoryGroup.OFFICE),
    # Security
    ("id_card", "ID Card", AssetCategoryGroup.SECURITY),
    ("access_card", "Access Card", AssetCategoryGroup.SECURITY),
    ("biometric_card", "Biometric Card", AssetCategoryGroup.SECURITY),
    ("gate_pass", "Gate Pass", AssetCategoryGroup.SECURITY),
    ("office_key", "Office Key", AssetCategoryGroup.SECURITY),
    ("sim_card", "SIM Card", AssetCategoryGroup.SECURITY),
    # Vehicles
    ("car", "Car", AssetCategoryGroup.VEHICLE),
    ("ambulance", "Ambulance", AssetCategoryGroup.VEHICLE),
    ("bus", "Bus", AssetCategoryGroup.VEHICLE),
    ("motorcycle", "Motorcycle", AssetCategoryGroup.VEHICLE),
    # Medical / Healthcare
    ("ultrasound_laptop", "Ultrasound Laptop", AssetCategoryGroup.MEDICAL),
    ("portable_ecg", "Portable ECG", AssetCategoryGroup.MEDICAL),
    ("barcode_scanner", "Barcode Scanner", AssetCategoryGroup.MEDICAL),
    ("dictation_mic", "Dictation Microphone", AssetCategoryGroup.MEDICAL),
]


class Command(BaseCommand):
    help = "Create default asset categories for enterprise asset management."

    def handle(self, *args, **options):
        created = 0
        for code, name, group in CATEGORIES:
            _, was_created = AssetCategory.objects.get_or_create(
                code=code, defaults={"name": name, "group": group},
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Asset categories ready ({created} new)."))
