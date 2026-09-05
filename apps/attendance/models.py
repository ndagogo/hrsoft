from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class DeviceBrand(models.TextChoices):
    ZKTECO = "zkteco", "ZKTeco"
    HIKVISION = "hikvision", "HikVision"
    OTHER = "other", "Other"


class DeviceConnectionMode(models.TextChoices):
    PULL = "pull", "Pull (HRMS polls the device)"
    PUSH = "push", "Push (device posts events to webhook)"
    BOTH = "both", "Both"


class BiometricDevice(models.Model):
    """
    Physical attendance terminal — ZKTeco (TCP port 4370), HikVision (ISAPI HTTP),
    or any vendor that pushes punches via the device-agnostic remote API.
    """
    name = models.CharField(max_length=100)
    brand = models.CharField(max_length=20, choices=DeviceBrand.choices, default=DeviceBrand.ZKTECO)
    connection_mode = models.CharField(
        max_length=10,
        choices=DeviceConnectionMode.choices,
        default=DeviceConnectionMode.PULL,
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Required for pull mode (LAN IP). Optional for remote API / push-only devices.",
    )
    port = models.PositiveIntegerField(
        default=4370,
        help_text="ZKTeco TCP COMM port is typically 4370. HikVision ISAPI is usually 80.",
    )
    username = models.CharField(max_length=50, default="admin", blank=True, help_text="HikVision ISAPI username")
    password = models.CharField(
        max_length=128,
        blank=True,
        help_text="HikVision ISAPI password (Digest auth).",
    )
    comm_key = models.PositiveIntegerField(
        default=0,
        help_text="ZKTeco communication key / device password (integer). Usually 0 unless changed on the device.",
    )

    location = models.CharField(max_length=120, blank=True, help_text="e.g. Main Gate, Floor 3 Entrance")
    serial_number = models.CharField(max_length=80, blank=True)
    webhook_token = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Per-device API / webhook secret. Used as Bearer token for remote push.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="When False, polling and device auth are disabled. Does not mean online.",
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, blank=True, help_text="ok / error / never")
    last_sync_message = models.CharField(max_length=255, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, help_text="Last successful API heartbeat or punch.")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        if self.ip_address:
            return f"{self.name} ({self.ip_address}:{self.port})"
        return f"{self.name} (remote API)"

    @property
    def isapi_base_url(self):
        if not self.ip_address:
            return ""
        return f"http://{self.ip_address}:{self.port}/ISAPI"

    @property
    def endpoint_label(self):
        if self.ip_address:
            return f"{self.ip_address}:{self.port}"
        return self.serial_number or "remote"

    @staticmethod
    def online_threshold() -> timedelta:
        cfg = getattr(settings, "BIOMETRIC_SETTINGS", {}) or {}
        minutes = int(cfg.get("ONLINE_THRESHOLD_MINUTES", 10))
        return timedelta(minutes=max(1, minutes))

    @property
    def is_online(self) -> bool:
        """True only when the device recently communicated (heartbeat, punch, or successful sync)."""
        if not self.last_seen_at:
            return False
        return timezone.now() - self.last_seen_at <= self.online_threshold()

    @property
    def connection_status(self) -> str:
        """UI label: online | offline."""
        return "online" if self.is_online else "offline"

    @property
    def connection_status_display(self) -> str:
        return "Online" if self.is_online else "Offline"

    @property
    def online_window_label(self) -> str:
        minutes = int(self.online_threshold().total_seconds() // 60)
        return f"{minutes} min"


class PunchDirection(models.TextChoices):
    IN = "in", "Check In"
    OUT = "out", "Check Out"
    UNKNOWN = "unknown", "Unknown"


class PunchSource(models.TextChoices):
    FACE = "face", "Face Recognition"
    FINGERPRINT = "fingerprint", "Fingerprint"
    CARD = "card", "Card"
    PASSWORD = "password", "Password"
    PIN = "pin", "PIN"
    QR = "qr", "QR Code"
    MANUAL = "manual", "Manual Entry"
    WEBHOOK = "webhook", "Device Webhook"
    API = "api", "Device API"


class RawPunchLog(models.Model):
    """
    Immutable, append-only record of every raw punch event as received
    from a biometric device - whether pulled via ISAPI/ZK polling, pushed
    via vendor webhook, or submitted through the device-agnostic remote API.
    AttendanceRecord rows are derived/aggregated from these.
    """
    device = models.ForeignKey(BiometricDevice, on_delete=models.SET_NULL, null=True, related_name="punch_logs")
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="punch_logs"
    )
    device_employee_no = models.CharField(max_length=50, help_text="Raw employeeNoString from device payload.")
    direction = models.CharField(max_length=10, choices=PunchDirection.choices, default=PunchDirection.UNKNOWN)
    source = models.CharField(max_length=20, choices=PunchSource.choices, default=PunchSource.FACE)
    timestamp = models.DateTimeField()
    event_id = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional vendor/event idempotency key. Prevents duplicate ingest when set.",
    )
    raw_payload = models.JSONField(default=dict, blank=True)
    matched = models.BooleanField(default=False, help_text="Whether device_employee_no matched a known Employee.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp"]),
            models.Index(fields=["device_employee_no"]),
            models.Index(fields=["event_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "event_id"],
                condition=~models.Q(event_id=""),
                name="uniq_punch_device_event_id",
            ),
        ]

    def __str__(self):
        return f"{self.device_employee_no} @ {self.timestamp:%Y-%m-%d %H:%M} ({self.get_direction_display()})"


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    LATE = "late", "Late"
    ABSENT = "absent", "Absent"
    HALF_DAY = "half_day", "Half Day"
    ON_LEAVE = "on_leave", "On Leave"
    HOLIDAY = "holiday", "Holiday"
    WEEKEND = "weekend", "Weekend"


class DeviceCommandType(models.TextChoices):
    PULL_STAFF = "pull_staff", "Pull staff IDs from device"
    PUSH_STAFF = "push_staff", "Push staff IDs to device"
    PULL_ATTENDANCE = "pull_attendance", "Pull attendance / punches from device"
    GET_INFO = "get_info", "Get device info"


class DeviceCommandStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent to device"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class DeviceCommand(models.Model):
    """
    Queued instruction from HRMS to a biometric device/bridge.
    Remote devices poll the Device Hub and execute pending commands.
    LAN devices (ZKTeco) are usually executed immediately by the server.
    """
    device = models.ForeignKey(BiometricDevice, on_delete=models.CASCADE, related_name="commands")
    command = models.CharField(max_length=40, choices=DeviceCommandType.choices)
    status = models.CharField(
        max_length=20, choices=DeviceCommandStatus.choices, default=DeviceCommandStatus.PENDING
    )
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="device_commands"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["device", "status"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.device_id}:{self.command} ({self.status})"


class DeviceStaffSnapshot(models.Model):
    """Last-known staff enrollment list reported by / pulled from a device."""
    device = models.ForeignKey(BiometricDevice, on_delete=models.CASCADE, related_name="staff_snapshots")
    staff_id = models.CharField(max_length=50, help_text="Device user / biometric ID")
    name = models.CharField(max_length=120, blank=True)
    card_no = models.CharField(max_length=40, blank=True)
    privilege = models.CharField(max_length=20, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    linked_employee = models.ForeignKey(
        "employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="device_enrollments"
    )
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("device", "staff_id")
        ordering = ["staff_id"]
        indexes = [models.Index(fields=["staff_id"])]

    def __str__(self):
        return f"{self.device_id}:{self.staff_id}"


class AttendanceRecord(models.Model):
    """
    One row per employee per calendar day - the day-level summary HR and
    managers actually look at, derived from RawPunchLog rows (or entered
    manually as a fallback when biometric data is unavailable).
    """
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="attendance_records")
    date = models.DateField()
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT)
    source = models.CharField(max_length=20, choices=PunchSource.choices, default=PunchSource.FACE)
    worked_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=255, blank=True)
    is_manual_override = models.BooleanField(default=False)
    overridden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="attendance_overrides"
    )

    class Meta:
        ordering = ["-date"]
        unique_together = ("employee", "date")
        indexes = [models.Index(fields=["-date"])]

    def __str__(self):
        return f"{self.employee.employee_id} - {self.date} - {self.get_status_display()}"
