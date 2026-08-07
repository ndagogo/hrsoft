from django.conf import settings
from django.db import models
from django.utils import timezone


class AssetCategoryGroup(models.TextChoices):
    IT = "it", "IT Assets"
    OFFICE = "office", "Office Assets"
    SECURITY = "security", "Security Assets"
    VEHICLE = "vehicle", "Vehicles"
    MEDICAL = "medical", "Medical / Healthcare Equipment"


class AssetCondition(models.TextChoices):
    EXCELLENT = "excellent", "Excellent"
    NEW = "new", "New"
    GOOD = "good", "Good"
    FAIR = "fair", "Fair"
    POOR = "poor", "Poor"
    DAMAGED = "damaged", "Damaged"


class AssetStatus(models.TextChoices):
    PENDING_APPROVAL = "pending_approval", "Pending Approval"
    AVAILABLE = "available", "Available"
    ASSIGNED = "assigned", "Assigned"
    RESERVED = "reserved", "Reserved"
    MAINTENANCE = "maintenance", "Under Maintenance"
    LOST = "lost", "Lost"
    DAMAGED = "damaged", "Damaged"
    DISPOSED = "disposed", "Disposed"
    RETIRED = "retired", "Retired"


class AssetHistoryEvent(models.TextChoices):
    PURCHASED = "purchased", "Purchased"
    REGISTERED = "registered", "Registered"
    APPROVED = "approved", "Approved"
    ASSIGNED = "assigned", "Assigned to Employee"
    RETURNED = "returned", "Returned by Employee"
    TRANSFERRED = "transferred", "Transferred"
    MAINTENANCE_OPENED = "maintenance_opened", "Maintenance Opened"
    MAINTENANCE_COMPLETED = "maintenance_completed", "Maintenance Completed"
    INSPECTED = "inspected", "Inspected"
    RESERVED = "reserved", "Reserved"
    DISPOSED = "disposed", "Disposed"
    RETIRED = "retired", "Retired"
    STATUS_CHANGED = "status_changed", "Status Changed"
    NOTE = "note", "Note Added"


class AssetRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUPERVISOR_APPROVED = "supervisor_approved", "Supervisor Approved"
    IT_APPROVED = "it_approved", "IT Approved"
    STORE_APPROVED = "store_approved", "Store Approved"
    ISSUED = "issued", "Issued"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class MaintenanceStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class AssetCategory(models.Model):
    """Hierarchical asset taxonomy — IT, Office, Security, Vehicle, Medical."""
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=30, unique=True)
    group = models.CharField(max_length=20, choices=AssetCategoryGroup.choices, default=AssetCategoryGroup.IT)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["group", "name"]
        verbose_name_plural = "asset categories"

    def __str__(self):
        return f"{self.name} ({self.get_group_display()})"


class Asset(models.Model):
    asset_number = models.CharField(max_length=50, unique=True, help_text="Internal asset number / tag")
    barcode = models.CharField(max_length=80, blank=True)
    rfid_tag = models.CharField(max_length=80, blank=True)
    name = models.CharField(max_length=150)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, related_name="assets")
    brand = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=80, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    manufacturer = models.CharField(max_length=100, blank=True)

    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vendor = models.CharField(max_length=150, blank=True)
    invoice_number = models.CharField(max_length=80, blank=True)

    warranty_start = models.DateField(null=True, blank=True)
    warranty_end = models.DateField(null=True, blank=True)
    amc_provider = models.CharField(max_length=150, blank=True)
    amc_expiry = models.DateField(null=True, blank=True)
    insurance_provider = models.CharField(max_length=150, blank=True)
    insurance_policy = models.CharField(max_length=80, blank=True)
    insurance_expiry = models.DateField(null=True, blank=True)

    condition = models.CharField(max_length=20, choices=AssetCondition.choices, default=AssetCondition.GOOD)
    status = models.CharField(max_length=25, choices=AssetStatus.choices, default=AssetStatus.PENDING_APPROVAL)
    branch = models.ForeignKey("organization.Branch", on_delete=models.SET_NULL, null=True, blank=True)
    location = models.CharField(max_length=150, blank=True, help_text="Room, floor, or site within branch")
    department = models.ForeignKey(
        "employees.Department", on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Cost centre / owning department",
    )

    notes = models.TextField(blank=True)
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assets_registered",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assets_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    next_maintenance_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset_number"]

    def __str__(self):
        return f"{self.asset_number} — {self.name}"

    @property
    def asset_tag(self):
        return self.asset_number

    @property
    def current_assignment(self):
        return self.assignments.filter(is_active=True).select_related("employee__user").first()

    @property
    def assigned_employee(self):
        a = self.current_assignment
        return a.employee if a else None

    @property
    def is_warranty_expiring_soon(self):
        if not self.warranty_end:
            return False
        return self.warranty_end <= (timezone.now().date() + timezone.timedelta(days=60))


class AssetAccessory(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="accessories")
    name = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=80, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "asset accessories"

    def __str__(self):
        return self.name


class AssetAssignment(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="assignments")
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="asset_assignments")
    department = models.ForeignKey("employees.Department", on_delete=models.SET_NULL, null=True, blank=True)
    assigned_date = models.DateField(default=timezone.now)
    expected_return_date = models.DateField(null=True, blank=True, help_text="Blank = permanent assignment")
    returned_date = models.DateField(null=True, blank=True)
    condition_on_assign = models.CharField(max_length=20, choices=AssetCondition.choices, default=AssetCondition.GOOD)
    condition_on_return = models.CharField(max_length=20, choices=AssetCondition.choices, blank=True)
    accessories_issued = models.TextField(blank=True, help_text="Charger, mouse, bag, etc.")
    notes = models.TextField(blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_assignments_made",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_assignments_approved",
    )
    received_acknowledged = models.BooleanField(default=False)
    received_at = models.DateTimeField(null=True, blank=True)
    inspection_notes = models.TextField(blank=True)
    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_inspections",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-assigned_date"]

    def __str__(self):
        return f"{self.asset.asset_number} → {self.employee.full_name}"


class AssetHistory(models.Model):
    """Immutable audit trail — records are never deleted."""
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="history")
    event_type = models.CharField(max_length=30, choices=AssetHistoryEvent.choices)
    summary = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_history_events",
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "asset history"

    def __str__(self):
        return f"{self.asset.asset_number}: {self.get_event_type_display()}"


class AssetMaintenance(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="maintenance_records")
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    problem = models.TextField()
    technician = models.CharField(max_length=120, blank=True)
    vendor = models.CharField(max_length=150, blank=True)
    repair_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=MaintenanceStatus.choices, default=MaintenanceStatus.OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    next_maintenance_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-opened_at"]

    def __str__(self):
        return f"Maintenance: {self.asset.asset_number}"


class AssetRequest(models.Model):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="asset_requests")
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, related_name="requests")
    title = models.CharField(max_length=150)
    justification = models.TextField()
    status = models.CharField(max_length=25, choices=AssetRequestStatus.choices, default=AssetRequestStatus.PENDING)
    supervisor_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_req_supervisor",
    )
    it_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_req_it",
    )
    store_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_req_store",
    )
    issued_asset = models.ForeignKey(Asset, on_delete=models.SET_NULL, null=True, blank=True, related_name="from_requests")
    rejection_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.employee.full_name})"


class AssetTransfer(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="transfers")
    from_employee = models.ForeignKey(
        "employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_transfers_from",
    )
    to_employee = models.ForeignKey(
        "employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_transfers_to",
    )
    from_department = models.ForeignKey(
        "employees.Department", on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_transfers_from_dept",
    )
    to_department = models.ForeignKey(
        "employees.Department", on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_transfers_to_dept",
    )
    transferred_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AssetDisposal(models.Model):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name="disposal")
    disposed_at = models.DateField()
    method = models.CharField(max_length=80, blank=True)
    reason = models.TextField()
    salvage_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    disposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
