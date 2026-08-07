from django.db import models
from django.conf import settings


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
    Physical attendance terminal — ZKTeco (TCP port 4370) or HikVision (ISAPI HTTP).
    """
    name = models.CharField(max_length=100)
    brand = models.CharField(max_length=20, choices=DeviceBrand.choices, default=DeviceBrand.ZKTECO)
    connection_mode = models.CharField(
        max_length=10,
        choices=DeviceConnectionMode.choices,
        default=DeviceConnectionMode.PULL,
    )

    ip_address = models.GenericIPAddressField(help_text="Static LAN IP, e.g. 192.168.1.201")
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
    webhook_token = models.CharField(max_length=64, blank=True, help_text="Per-device shared secret for push events.")

    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, blank=True, help_text="ok / error / never")
    last_sync_message = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.ip_address}:{self.port})"

    @property
    def isapi_base_url(self):
        return f"http://{self.ip_address}:{self.port}/ISAPI"

    @property
    def endpoint_label(self):
        return f"{self.ip_address}:{self.port}"


class PunchDirection(models.TextChoices):
    IN = "in", "Check In"
    OUT = "out", "Check Out"
    UNKNOWN = "unknown", "Unknown"


class PunchSource(models.TextChoices):
    FACE = "face", "Face Recognition"
    FINGERPRINT = "fingerprint", "Fingerprint"
    CARD = "card", "Card"
    PASSWORD = "password", "Password"
    MANUAL = "manual", "Manual Entry"
    WEBHOOK = "webhook", "Device Webhook"


class RawPunchLog(models.Model):
    """
    Immutable, append-only record of every raw punch event as received
    from a biometric device - whether pulled via ISAPI polling or pushed
    via webhook. AttendanceRecord rows are derived/aggregated from these.
    Keeping raw + derived separate means re-processing logic can be
    re-run without losing source data.
    """
    device = models.ForeignKey(BiometricDevice, on_delete=models.SET_NULL, null=True, related_name="punch_logs")
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="punch_logs"
    )
    device_employee_no = models.CharField(max_length=50, help_text="Raw employeeNoString from device payload.")
    direction = models.CharField(max_length=10, choices=PunchDirection.choices, default=PunchDirection.UNKNOWN)
    source = models.CharField(max_length=20, choices=PunchSource.choices, default=PunchSource.FACE)
    timestamp = models.DateTimeField()
    raw_payload = models.JSONField(default=dict, blank=True)
    matched = models.BooleanField(default=False, help_text="Whether device_employee_no matched a known Employee.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp"]),
            models.Index(fields=["device_employee_no"]),
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
