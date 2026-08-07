# Enterprise asset management upgrade

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def seed_categories(apps, schema_editor):
    AssetCategory = apps.get_model("assets", "AssetCategory")
    rows = [
        ("it", "laptop", "Laptop"), ("it", "desktop", "Desktop"), ("it", "tablet", "Tablet"),
        ("it", "phone", "Phone"), ("it", "printer", "Printer"), ("it", "scanner", "Scanner"),
        ("it", "server", "Server"), ("it", "router", "Router"), ("it", "switch", "Network Switch"),
        ("it", "ups", "UPS"), ("it", "projector", "Projector"), ("it", "monitor", "Workstation Monitor"),
        ("office", "chair", "Chair"), ("office", "table", "Table"), ("office", "cabinet", "Cabinet"),
        ("office", "whiteboard", "Whiteboard"),
        ("security", "id_card", "ID Card"), ("security", "access_card", "Access Card"),
        ("security", "biometric_card", "Biometric Card"), ("security", "gate_pass", "Gate Pass"),
        ("security", "office_key", "Office Key"), ("security", "sim_card", "SIM Card"),
        ("vehicle", "car", "Car"), ("vehicle", "ambulance", "Ambulance"), ("vehicle", "bus", "Bus"),
        ("vehicle", "motorcycle", "Motorcycle"),
        ("medical", "ultrasound_laptop", "Ultrasound Laptop"), ("medical", "portable_ecg", "Portable ECG"),
        ("medical", "barcode_scanner", "Barcode Scanner"), ("medical", "dictation_mic", "Dictation Microphone"),
    ]
    for group, code, name in rows:
        AssetCategory.objects.get_or_create(code=code, defaults={"name": name, "group": group})


def map_asset_types(apps, schema_editor):
    Asset = apps.get_model("assets", "Asset")
    AssetCategory = apps.get_model("assets", "AssetCategory")
    mapping = {
        "laptop": "laptop", "desktop": "desktop", "phone": "phone",
        "vehicle": "car", "id_card": "id_card", "sim": "sim_card", "other": "laptop",
    }
    default = AssetCategory.objects.filter(code="laptop").first()
    for asset in Asset.objects.order_by("pk"):
        code = mapping.get(getattr(asset, "asset_type", "other"), "laptop")
        cat = AssetCategory.objects.filter(code=code).first() or default
        asset.category_id = cat.pk if cat else None
        if not asset.asset_number:
            asset.asset_number = f"AST-{asset.pk:04d}"
        asset.is_active = True
        asset.save(update_fields=["category_id", "asset_number", "is_active"])


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0002_enterprise_upgrade"),
        ("employees", "0002_enterprise_upgrade"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("code", models.CharField(max_length=30, unique=True)),
                ("group", models.CharField(
                    choices=[
                        ("it", "IT Assets"), ("office", "Office Assets"), ("security", "Security Assets"),
                        ("vehicle", "Vehicles"), ("medical", "Medical / Healthcare Equipment"),
                    ],
                    default="it", max_length=20,
                )),
                ("description", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["group", "name"], "verbose_name_plural": "asset categories"},
        ),
        migrations.RunPython(seed_categories, migrations.RunPython.noop),
        migrations.RenameField(model_name="asset", old_name="asset_tag", new_name="asset_number"),
        migrations.RenameField(model_name="asset", old_name="purchase_cost", new_name="purchase_price"),
        migrations.AddField(model_name="asset", name="barcode", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="asset", name="rfid_tag", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="asset", name="manufacturer", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="asset", name="vendor", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="asset", name="invoice_number", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="asset", name="warranty_start", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="asset", name="warranty_end", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="asset", name="amc_provider", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="asset", name="amc_expiry", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="asset", name="insurance_provider", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="asset", name="insurance_policy", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="asset", name="insurance_expiry", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="asset", name="location", field=models.CharField(blank=True, help_text="Room, floor, or site within branch", max_length=150)),
        migrations.AddField(model_name="asset", name="next_maintenance_date", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="asset", name="is_active", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="asset", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.AddField(model_name="asset", name="approved_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(
            model_name="asset", name="approved_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assets_approved", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="asset", name="department",
            field=models.ForeignKey(blank=True, help_text="Cost centre / owning department", null=True, on_delete=django.db.models.deletion.SET_NULL, to="employees.department"),
        ),
        migrations.AddField(
            model_name="asset", name="registered_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assets_registered", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="asset", name="category",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="assets", to="assets.assetcategory"),
        ),
        migrations.AlterModelOptions(name="asset", options={"ordering": ["asset_number"]}),
        migrations.RunPython(map_asset_types, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="asset", name="category",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assets", to="assets.assetcategory"),
        ),
        migrations.RemoveField(model_name="asset", name="asset_type"),
        migrations.AlterField(
            model_name="asset", name="asset_number",
            field=models.CharField(help_text="Internal asset number / tag", max_length=50, unique=True),
        ),
        migrations.AlterField(
            model_name="asset", name="condition",
            field=models.CharField(choices=[
                ("excellent", "Excellent"), ("new", "New"), ("good", "Good"),
                ("fair", "Fair"), ("poor", "Poor"), ("damaged", "Damaged"),
            ], default="good", max_length=20),
        ),
        migrations.AlterField(
            model_name="asset", name="status",
            field=models.CharField(choices=[
                ("pending_approval", "Pending Approval"), ("available", "Available"),
                ("assigned", "Assigned"), ("reserved", "Reserved"), ("maintenance", "Under Maintenance"),
                ("lost", "Lost"), ("damaged", "Damaged"), ("disposed", "Disposed"), ("retired", "Retired"),
            ], default="pending_approval", max_length=25),
        ),
        migrations.AddField(model_name="assetassignment", name="accessories_issued", field=models.TextField(blank=True, help_text="Charger, mouse, bag, etc.")),
        migrations.AddField(model_name="assetassignment", name="expected_return_date", field=models.DateField(blank=True, help_text="Blank = permanent assignment", null=True)),
        migrations.AddField(model_name="assetassignment", name="inspection_notes", field=models.TextField(blank=True)),
        migrations.AddField(model_name="assetassignment", name="received_acknowledged", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="assetassignment", name="received_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="assetassignment", name="created_at", field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now)),
        migrations.AlterField(model_name="assetassignment", name="created_at", field=models.DateTimeField(auto_now_add=True)),
        migrations.AddField(
            model_name="assetassignment", name="assigned_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_assignments_made", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="assetassignment", name="approved_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_assignments_approved", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="assetassignment", name="department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="employees.department"),
        ),
        migrations.AddField(
            model_name="assetassignment", name="inspected_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_inspections", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="assetassignment", name="assigned_date",
            field=models.DateField(default=django.utils.timezone.now),
        ),
        migrations.AlterField(
            model_name="assetassignment", name="condition_on_assign",
            field=models.CharField(choices=[
                ("excellent", "Excellent"), ("new", "New"), ("good", "Good"),
                ("fair", "Fair"), ("poor", "Poor"), ("damaged", "Damaged"),
            ], default="good", max_length=20),
        ),
        migrations.AlterField(
            model_name="assetassignment", name="condition_on_return",
            field=models.CharField(blank=True, choices=[
                ("excellent", "Excellent"), ("new", "New"), ("good", "Good"),
                ("fair", "Fair"), ("poor", "Poor"), ("damaged", "Damaged"),
            ], max_length=20),
        ),
        migrations.CreateModel(
            name="AssetAccessory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("serial_number", models.CharField(blank=True, max_length=80)),
                ("notes", models.CharField(blank=True, max_length=255)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="accessories", to="assets.asset")),
            ],
            options={"ordering": ["name"], "verbose_name_plural": "asset accessories"},
        ),
        migrations.CreateModel(
            name="AssetHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[
                    ("purchased", "Purchased"), ("registered", "Registered"), ("approved", "Approved"),
                    ("assigned", "Assigned to Employee"), ("returned", "Returned by Employee"),
                    ("transferred", "Transferred"), ("maintenance_opened", "Maintenance Opened"),
                    ("maintenance_completed", "Maintenance Completed"), ("inspected", "Inspected"),
                    ("reserved", "Reserved"), ("disposed", "Disposed"), ("retired", "Retired"),
                    ("status_changed", "Status Changed"), ("note", "Note Added"),
                ], max_length=30)),
                ("summary", models.CharField(max_length=255)),
                ("detail", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="history", to="assets.asset")),
                ("employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_history_events", to="employees.employee")),
            ],
            options={"ordering": ["-created_at"], "verbose_name_plural": "asset history"},
        ),
        migrations.CreateModel(
            name="AssetMaintenance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("problem", models.TextField()),
                ("technician", models.CharField(blank=True, max_length=120)),
                ("vendor", models.CharField(blank=True, max_length=150)),
                ("repair_cost", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("status", models.CharField(choices=[
                    ("open", "Open"), ("in_progress", "In Progress"),
                    ("completed", "Completed"), ("cancelled", "Cancelled"),
                ], default="open", max_length=20)),
                ("opened_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("next_maintenance_date", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="maintenance_records", to="assets.asset")),
                ("reported_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-opened_at"]},
        ),
        migrations.CreateModel(
            name="AssetRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=150)),
                ("justification", models.TextField()),
                ("status", models.CharField(choices=[
                    ("pending", "Pending"), ("supervisor_approved", "Supervisor Approved"),
                    ("it_approved", "IT Approved"), ("store_approved", "Store Approved"),
                    ("issued", "Issued"), ("rejected", "Rejected"), ("cancelled", "Cancelled"),
                ], default="pending", max_length=25)),
                ("rejection_note", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="requests", to="assets.assetcategory")),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="asset_requests", to="employees.employee")),
                ("issued_asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="from_requests", to="assets.asset")),
                ("it_approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_req_it", to=settings.AUTH_USER_MODEL)),
                ("store_approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_req_store", to=settings.AUTH_USER_MODEL)),
                ("supervisor_approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_req_supervisor", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AssetTransfer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transfers", to="assets.asset")),
                ("from_department", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_transfers_from_dept", to="employees.department")),
                ("from_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_transfers_from", to="employees.employee")),
                ("to_department", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_transfers_to_dept", to="employees.department")),
                ("to_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="asset_transfers_to", to="employees.employee")),
                ("transferred_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AssetDisposal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("disposed_at", models.DateField()),
                ("method", models.CharField(blank=True, max_length=80)),
                ("reason", models.TextField()),
                ("salvage_value", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("asset", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="disposal", to="assets.asset")),
                ("disposed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
