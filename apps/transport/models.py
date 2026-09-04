"""
Transportation & Fleet Management — Phase 1 core models.

Architecture:
  Ride  = one physical vehicle journey (not a single booking)
  RidePassenger = independent passenger participation / journey status
  RideStop = ordered physical stops on the route
  RideEvent = immutable operational timeline
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

class VehicleStatus(models.TextChoices):
    AVAILABLE = "available", "Available"
    IN_USE = "in_use", "In use"
    MAINTENANCE = "maintenance", "Maintenance"
    RETIRED = "retired", "Retired"


class VehicleType(models.TextChoices):
    SEDAN = "sedan", "Sedan"
    SUV = "suv", "SUV"
    BUS = "bus", "Bus / Hiace"
    VAN = "van", "Van"
    TRUCK = "truck", "Truck"
    OTHER = "other", "Other"


class DriverStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    SUSPENDED = "suspended", "Suspended"


class RideType(models.TextChoices):
    OFFICIAL = "official", "Official trip"
    CARPOOL = "carpool", "Carpool"
    SHUTTLE = "shuttle", "Shuttle"
    EXECUTIVE = "executive", "Executive"
    AIRPORT = "airport", "Airport transfer"
    INTER_BRANCH = "inter_branch", "Inter-branch"
    OTHER = "other", "Other"


class RideStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    APPROVED = "approved", "Approved"
    DRIVER_PENDING = "driver_pending", "Awaiting driver"
    DRIVER_ACCEPTED = "driver_accepted", "Driver accepted"
    READY = "ready", "Ready"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"
    ABORTED = "aborted", "Aborted"


class PassengerStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    CONFIRMED = "confirmed", "Confirmed"
    BOARDING = "boarding", "Boarding"
    ONBOARD = "onboard", "On board"
    ARRIVED = "arrived", "Arrived"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"
    NO_SHOW = "no_show", "No show"


class ApprovalStage(models.TextChoices):
    MANAGER = "manager", "Department Manager"
    TRANSPORT = "transport", "Transport Officer"


class StepStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    PENDING = "pending", "Awaiting action"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    SKIPPED = "skipped", "Skipped"


class JoinRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ORGANIZER_APPROVED = "organizer_approved", "Organizer approved"
    ADMIN_APPROVED = "admin_approved", "Admin approved"
    CONFIRMED = "confirmed", "Confirmed"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class RideEventType(models.TextChoices):
    CREATED = "created", "Created"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    DRIVER_ASSIGNED = "driver_assigned", "Driver assigned"
    DRIVER_ACCEPTED = "driver_accepted", "Driver accepted"
    DRIVER_DECLINED = "driver_declined", "Driver declined"
    PASSENGER_ADDED = "passenger_added", "Passenger added"
    PASSENGER_REMOVED = "passenger_removed", "Passenger removed"
    JOIN_REQUESTED = "join_requested", "Join requested"
    JOIN_CONFIRMED = "join_confirmed", "Join confirmed"
    READY = "ready", "Marked ready"
    STARTED = "started", "Journey started"
    STOP_ARRIVED = "stop_arrived", "Stop arrived"
    PASSENGER_ARRIVED = "passenger_arrived", "Passenger arrived"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    NOTE = "note", "Note"


# Default approval chain for Phase 1 (configurable later via TransportationPolicy)
DEFAULT_APPROVAL_CHAIN = (ApprovalStage.MANAGER, ApprovalStage.TRANSPORT)

RIDE_TRANSITIONS = {
    RideStatus.DRAFT: {RideStatus.SUBMITTED, RideStatus.CANCELLED},
    RideStatus.SUBMITTED: {RideStatus.PENDING_APPROVAL, RideStatus.CANCELLED},
    RideStatus.PENDING_APPROVAL: {
        RideStatus.APPROVED, RideStatus.REJECTED, RideStatus.CANCELLED,
    },
    RideStatus.APPROVED: {RideStatus.DRIVER_PENDING, RideStatus.CANCELLED},
    RideStatus.DRIVER_PENDING: {
        RideStatus.DRIVER_ACCEPTED, RideStatus.APPROVED, RideStatus.CANCELLED,
    },
    RideStatus.DRIVER_ACCEPTED: {RideStatus.READY, RideStatus.IN_PROGRESS, RideStatus.CANCELLED},
    RideStatus.READY: {RideStatus.IN_PROGRESS, RideStatus.CANCELLED},
    RideStatus.IN_PROGRESS: {RideStatus.COMPLETED, RideStatus.ABORTED},
    RideStatus.COMPLETED: set(),
    RideStatus.REJECTED: set(),
    RideStatus.CANCELLED: set(),
    RideStatus.ABORTED: set(),
}


# ---------------------------------------------------------------------------
# Fleet
# ---------------------------------------------------------------------------

class Vehicle(models.Model):
    name = models.CharField(max_length=120, help_text="Display name, e.g. Toyota Hiace – HQ Shuttle")
    registration_number = models.CharField(max_length=40, unique=True)
    vehicle_type = models.CharField(max_length=20, choices=VehicleType.choices, default=VehicleType.BUS)
    make = models.CharField(max_length=60, blank=True)
    model_name = models.CharField(max_length=60, blank=True, verbose_name="Model")
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    color = models.CharField(max_length=40, blank=True)
    capacity = models.PositiveSmallIntegerField(
        default=14,
        help_text="Maximum passengers (excluding driver).",
    )
    branch = models.ForeignKey(
        "organization.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles",
    )
    status = models.CharField(max_length=20, choices=VehicleStatus.choices, default=VehicleStatus.AVAILABLE)
    gps_device_id = models.CharField(max_length=80, blank=True, help_text="Optional dedicated tracker ID.")
    photo = models.ImageField(
        upload_to="transport/vehicles/photos/%Y/%m/",
        blank=True,
        null=True,
        help_text="Optional photo of the vehicle.",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.registration_number})"

    @property
    def photo_url(self):
        if self.photo:
            return self.photo.url
        return ""


class Driver(models.Model):
    employee = models.OneToOneField(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="driver_profile",
    )
    license_number = models.CharField(max_length=60, blank=True)
    license_expiry = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=DriverStatus.choices, default=DriverStatus.ACTIVE)
    default_vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_drivers",
    )
    phone_override = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__user__first_name", "employee__user__last_name"]

    def __str__(self):
        return self.employee.full_name if hasattr(self.employee, "full_name") else str(self.employee)

    @property
    def display_phone(self):
        return self.phone_override or getattr(self.employee.user, "phone_number", "") or ""


class VehicleDocument(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=120)
    document_type = models.CharField(
        max_length=40,
        choices=[
            ("insurance", "Insurance"),
            ("roadworthiness", "Roadworthiness"),
            ("registration", "Registration"),
            ("other", "Other"),
        ],
        default="other",
    )
    file = models.FileField(upload_to="transport/vehicles/%Y/%m/", blank=True)
    expires_on = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.title} — {self.vehicle.registration_number}"


class TransportationPolicy(models.Model):
    """Singleton-style org policy (one active row expected)."""
    name = models.CharField(max_length=80, default="Default")
    is_active = models.BooleanField(default=True)
    require_manager_approval = models.BooleanField(default=True)
    require_transport_approval = models.BooleanField(default=True)
    require_driver_acceptance = models.BooleanField(default=True)
    allow_carpooling = models.BooleanField(default=True)
    max_route_deviation_percent = models.PositiveSmallIntegerField(default=20)
    geofence_radius_metres = models.PositiveIntegerField(default=100)
    auto_start_enabled = models.BooleanField(default=False)
    auto_arrival_enabled = models.BooleanField(default=False)
    min_booking_notice_hours = models.PositiveSmallIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "transportation policies"

    def __str__(self):
        return self.name

    @classmethod
    def current(cls):
        obj = cls.objects.filter(is_active=True).order_by("-id").first()
        if obj:
            return obj
        return cls.objects.create(name="Default", is_active=True)


# ---------------------------------------------------------------------------
# Rides
# ---------------------------------------------------------------------------

class Ride(models.Model):
    reference = models.CharField(max_length=20, unique=True, db_index=True)
    ride_type = models.CharField(max_length=20, choices=RideType.choices, default=RideType.OFFICIAL)
    status = models.CharField(
        max_length=30, choices=RideStatus.choices, default=RideStatus.DRAFT, db_index=True,
    )
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="rides_organized",
        help_text="Transport officer or employee who owns this ride (not always a passenger).",
    )
    requester = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rides_requested",
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.PROTECT, related_name="rides", null=True, blank=True,
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name="rides",
    )
    purpose = models.CharField(max_length=255, blank=True)
    origin_label = models.CharField(max_length=255)
    origin_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    origin_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    scheduled_departure = models.DateTimeField()
    scheduled_return = models.DateTimeField(null=True, blank=True)
    estimated_distance_km = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    estimated_duration_min = models.PositiveIntegerField(null=True, blank=True)
    route_geometry = models.JSONField(
        default=dict,
        blank=True,
        help_text="GeoJSON LineString from the routing provider.",
    )
    route_provider = models.CharField(max_length=40, blank=True)
    actual_start_at = models.DateTimeField(null=True, blank=True)
    actual_end_at = models.DateTimeField(null=True, blank=True)
    current_stage = models.CharField(max_length=20, choices=ApprovalStage.choices, blank=True)
    allow_carpool = models.BooleanField(default=True)
    seats_reserved = models.PositiveSmallIntegerField(
        default=0,
        help_text="Confirmed passenger seats currently held.",
    )
    notes = models.TextField(blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-scheduled_departure", "-created_at"]

    def __str__(self):
        return f"{self.reference} — {self.origin_label}"

    @property
    def capacity(self):
        return self.vehicle.capacity if self.vehicle_id else 0

    @property
    def seats_available(self):
        return max(0, self.capacity - self.seats_reserved)

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in RIDE_TRANSITIONS.get(self.status, set())


class RideStop(models.Model):
    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="stops")
    sequence = models.PositiveSmallIntegerField(default=1)
    label = models.CharField(max_length=255)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    planned_arrival = models.DateTimeField(null=True, blank=True)
    actual_arrival = models.DateTimeField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["ride", "sequence"]
        unique_together = ("ride", "sequence")

    def __str__(self):
        return f"Stop {self.sequence}: {self.label}"


class RidePassenger(models.Model):
    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="passengers")
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="ride_participations",
    )
    stop = models.ForeignKey(
        RideStop,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="passengers",
        help_text="Drop-off stop for this passenger.",
    )
    destination_label = models.CharField(max_length=255)
    destination_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    destination_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(
        max_length=30, choices=PassengerStatus.choices, default=PassengerStatus.REQUESTED, db_index=True,
    )
    boarded_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    arrival_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    arrival_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        unique_together = ("ride", "employee")

    def __str__(self):
        return f"{self.employee} → {self.destination_label}"


class RideApprovalStep(models.Model):
    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="approval_steps")
    stage = models.CharField(max_length=20, choices=ApprovalStage.choices)
    sequence = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=StepStatus.choices, default=StepStatus.WAITING)
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    note = models.CharField(max_length=255, blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sequence"]
        unique_together = ("ride", "stage")

    def __str__(self):
        return f"{self.ride.reference} / {self.stage} / {self.status}"

    def mark_pending(self):
        self.status = StepStatus.PENDING
        self.save(update_fields=["status"])

    def approve(self, user, note=""):
        self.status = StepStatus.APPROVED
        self.acted_by = user
        self.note = note or ""
        self.acted_at = timezone.now()
        self.save(update_fields=["status", "acted_by", "note", "acted_at"])

    def reject(self, user, note=""):
        self.status = StepStatus.REJECTED
        self.acted_by = user
        self.note = note or "Rejected"
        self.acted_at = timezone.now()
        self.save(update_fields=["status", "acted_by", "note", "acted_at"])


class JoinRequest(models.Model):
    """Carpool join: needs organizer + transport admin approval (order-independent)."""
    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="join_requests")
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="ride_join_requests",
    )
    destination_label = models.CharField(max_length=255)
    destination_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    destination_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(
        max_length=30, choices=JoinRequestStatus.choices, default=JoinRequestStatus.PENDING,
    )
    organizer_approved = models.BooleanField(null=True, blank=True)
    admin_approved = models.BooleanField(null=True, blank=True)
    organizer_acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="join_requests_organizer",
    )
    admin_acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="join_requests_admin",
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("ride", "employee")

    def __str__(self):
        return f"Join {self.employee} → {self.ride.reference}"


class RideEvent(models.Model):
    """Immutable operational timeline (not the security audit log)."""
    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=40, choices=RideEventType.choices)
    message = models.CharField(max_length=255)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    passenger = models.ForeignKey(
        RidePassenger, on_delete=models.SET_NULL, null=True, blank=True, related_name="events",
    )
    stop = models.ForeignKey(
        RideStop, on_delete=models.SET_NULL, null=True, blank=True, related_name="events",
    )
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.ride.reference}: {self.event_type}"


class LocationPing(models.Model):
    """GPS sample from driver PWA or dedicated tracker (Phase 4 ready)."""
    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="location_pings")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="location_pings")
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    speed_kmh = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    accuracy_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    source = models.CharField(
        max_length=20,
        choices=[("driver_pwa", "Driver PWA"), ("tracker", "GPS Tracker"), ("manual", "Manual")],
        default="driver_pwa",
    )

    class Meta:
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"{self.vehicle_id} @ {self.recorded_at}"
