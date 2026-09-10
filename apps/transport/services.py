"""Ride lifecycle, approvals, capacity, carpool join — domain services."""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.permissions import user_has_permission
from apps.notifications.services import deliver_notification

from .models import (
    DEFAULT_APPROVAL_CHAIN,
    ApprovalStage,
    JoinRequest,
    JoinRequestStatus,
    LocationPing,
    PassengerStatus,
    Ride,
    RideApprovalStep,
    RideEvent,
    RideEventType,
    RidePassenger,
    RideStatus,
    RideStop,
    RideType,
    StepStatus,
    TransportationPolicy,
    Vehicle,
    VehicleStatus,
)
from .routing import GeoPoint, estimate_route_or_fallback, haversine_metres


ACTIVE_RIDE_STATUSES = [
    RideStatus.APPROVED,
    RideStatus.DRIVER_PENDING,
    RideStatus.DRIVER_ACCEPTED,
    RideStatus.READY,
    RideStatus.IN_PROGRESS,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def next_ride_reference() -> str:
    year = timezone.now().year
    prefix = f"RID-{year}-"
    last = (
        Ride.objects.filter(reference__startswith=prefix)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.split("-")[-1]) + 1
        except ValueError:
            seq = Ride.objects.filter(reference__startswith=prefix).count() + 1
    return f"{prefix}{seq:05d}"


def record_event(ride, event_type, message, actor=None, passenger=None, stop=None, lat=None, lng=None, **meta):
    return RideEvent.objects.create(
        ride=ride,
        event_type=event_type,
        message=message[:255],
        actor=actor,
        passenger=passenger,
        stop=stop,
        lat=lat,
        lng=lng,
        meta=meta or {},
    )


def refresh_seats_reserved(ride: Ride) -> int:
    confirmed = ride.passengers.filter(
        status__in=[
            PassengerStatus.CONFIRMED,
            PassengerStatus.BOARDING,
            PassengerStatus.ONBOARD,
            PassengerStatus.ARRIVED,
        ]
    ).count()
    Ride.objects.filter(pk=ride.pk).update(seats_reserved=confirmed)
    ride.seats_reserved = confirmed
    return confirmed


def vehicle_is_available(vehicle: Vehicle, start, end, exclude_ride_id=None) -> bool:
    """Server-side overlap check for vehicle scheduling."""
    if not vehicle or not vehicle.is_active:
        return False
    if vehicle.status in (VehicleStatus.RETIRED, VehicleStatus.MAINTENANCE):
        return False
    end = end or (start + timedelta(hours=4))
    qs = Ride.objects.filter(
        vehicle=vehicle,
        status__in=ACTIVE_RIDE_STATUSES + [
            RideStatus.PENDING_APPROVAL, RideStatus.SUBMITTED, RideStatus.DRAFT,
        ],
    ).only("scheduled_departure", "scheduled_return")
    if exclude_ride_id:
        qs = qs.exclude(pk=exclude_ride_id)
    for r in qs:
        r_end = r.scheduled_return or (r.scheduled_departure + timedelta(hours=4))
        if r.scheduled_departure < end and r_end > start:
            return False
    return True


def approval_chain_for_policy(policy: TransportationPolicy | None = None):
    policy = policy or TransportationPolicy.current()
    chain = []
    if policy.require_manager_approval:
        chain.append(ApprovalStage.MANAGER)
    if policy.require_transport_approval:
        chain.append(ApprovalStage.TRANSPORT)
    return tuple(chain) or (ApprovalStage.TRANSPORT,)


# ---------------------------------------------------------------------------
# Create / submit
# ---------------------------------------------------------------------------

@transaction.atomic
def create_ride_request(
    *,
    organizer,
    requester_employee,
    vehicle,
    origin_label,
    destination_label,
    scheduled_departure,
    purpose="",
    driver=None,
    scheduled_return=None,
    estimated_distance_km=None,
    estimated_duration_min=None,
    origin_lat=None,
    origin_lng=None,
    destination_lat=None,
    destination_lng=None,
    allow_carpool=True,
    ride_type="official",
    route_geometry=None,
    route_provider="",
):
    if not vehicle_is_available(vehicle, scheduled_departure, scheduled_return):
        raise ValueError("Vehicle is not available for the selected time window.")

    policy = TransportationPolicy.current()
    ride = Ride.objects.create(
        reference=next_ride_reference(),
        ride_type=ride_type,
        status=RideStatus.DRAFT,
        organizer=organizer,
        requester=requester_employee,
        vehicle=vehicle,
        driver=driver or vehicle.default_drivers.first(),
        purpose=purpose,
        origin_label=origin_label,
        origin_lat=origin_lat,
        origin_lng=origin_lng,
        scheduled_departure=scheduled_departure,
        scheduled_return=scheduled_return,
        estimated_distance_km=estimated_distance_km,
        estimated_duration_min=estimated_duration_min,
        route_geometry=route_geometry or {},
        route_provider=route_provider or "",
        allow_carpool=allow_carpool and policy.allow_carpooling,
    )
    stop = RideStop.objects.create(
        ride=ride,
        sequence=1,
        label=destination_label,
        lat=destination_lat,
        lng=destination_lng,
    )
    passenger = None
    if requester_employee:
        passenger = RidePassenger.objects.create(
            ride=ride,
            employee=requester_employee,
            stop=stop,
            destination_label=destination_label,
            destination_lat=destination_lat,
            destination_lng=destination_lng,
            status=PassengerStatus.REQUESTED,
        )
    record_event(
        ride, RideEventType.CREATED,
        f"Ride draft created by {organizer.get_full_name() or organizer.username}",
        actor=organizer,
        passenger=passenger,
    )
    return ride


@transaction.atomic
def create_shuttle_ride(
    *,
    organizer,
    vehicle,
    origin_label,
    scheduled_departure,
    passengers: list[dict],
    purpose="",
    driver=None,
    scheduled_return=None,
    origin_lat=None,
    origin_lng=None,
    allow_carpool=False,
    estimated_distance_km=None,
    estimated_duration_min=None,
    route_geometry=None,
    route_provider="",
    submit=True,
):
    """
    Organizer-owned shuttle / multi-passenger journey.
    passengers: [{employee, destination_label, destination_lat?, destination_lng?}, ...]
    """
    if not passengers:
        raise ValueError("Add at least one passenger.")
    if vehicle.capacity and len(passengers) > vehicle.capacity:
        raise ValueError(f"Too many passengers for vehicle capacity ({vehicle.capacity}).")
    if not vehicle_is_available(vehicle, scheduled_departure, scheduled_return):
        raise ValueError("Vehicle is not available for the selected time window.")

    # Deduplicate employees
    seen = set()
    clean = []
    for row in passengers:
        emp = row["employee"]
        if emp.pk in seen:
            raise ValueError(f"Duplicate passenger: {emp}")
        seen.add(emp.pk)
        clean.append(row)

    policy = TransportationPolicy.current()
    ride = Ride.objects.create(
        reference=next_ride_reference(),
        ride_type=RideType.SHUTTLE,
        status=RideStatus.DRAFT,
        organizer=organizer,
        requester=None,
        vehicle=vehicle,
        driver=driver or vehicle.default_drivers.first(),
        purpose=purpose or "Company shuttle",
        origin_label=origin_label,
        origin_lat=origin_lat,
        origin_lng=origin_lng,
        scheduled_departure=scheduled_departure,
        scheduled_return=scheduled_return,
        estimated_distance_km=estimated_distance_km,
        estimated_duration_min=estimated_duration_min,
        route_geometry=route_geometry or {},
        route_provider=route_provider or "",
        allow_carpool=allow_carpool and policy.allow_carpooling,
    )

    # Group passengers by destination label → shared RideStop
    stop_by_key = {}
    seq = 0
    for row in clean:
        key = (row["destination_label"] or "").strip().lower()
        if key not in stop_by_key:
            seq += 1
            stop_by_key[key] = RideStop.objects.create(
                ride=ride,
                sequence=seq,
                label=row["destination_label"],
                lat=row.get("destination_lat"),
                lng=row.get("destination_lng"),
            )
        stop = stop_by_key[key]
        RidePassenger.objects.create(
            ride=ride,
            employee=row["employee"],
            stop=stop,
            destination_label=row["destination_label"],
            destination_lat=row.get("destination_lat"),
            destination_lng=row.get("destination_lng"),
            status=PassengerStatus.REQUESTED,
        )

    record_event(
        ride, RideEventType.CREATED,
        f"Shuttle created with {len(clean)} passenger(s) by {organizer.get_full_name() or organizer.username}",
        actor=organizer,
    )
    refresh_seats_reserved(ride)
    if submit:
        submit_ride(ride, organizer)
    return ride


@transaction.atomic
def apply_route_estimate(ride: Ride) -> Ride:
    """Recompute distance/ETA/geometry from origin + ordered stops with coordinates."""
    from .routing import GeoPoint, estimate_route_or_fallback

    if ride.origin_lat is None or ride.origin_lng is None:
        return ride
    points = [
        GeoPoint(float(ride.origin_lat), float(ride.origin_lng), ride.origin_label),
    ]
    for stop in ride.stops.order_by("sequence"):
        if stop.lat is not None and stop.lng is not None:
            points.append(GeoPoint(float(stop.lat), float(stop.lng), stop.label))
    if len(points) < 2:
        return ride
    result = estimate_route_or_fallback(points)
    ride.estimated_distance_km = result.distance_km
    ride.estimated_duration_min = result.duration_min
    ride.route_geometry = result.geometry
    ride.route_provider = result.provider
    ride.save(update_fields=[
        "estimated_distance_km", "estimated_duration_min",
        "route_geometry", "route_provider", "updated_at",
    ])
    return ride


@transaction.atomic
def submit_ride(ride: Ride, actor):
    if ride.status != RideStatus.DRAFT:
        raise ValueError("Only draft rides can be submitted.")
    ride.status = RideStatus.SUBMITTED
    ride.save(update_fields=["status", "updated_at"])
    record_event(ride, RideEventType.SUBMITTED, "Ride submitted for approval", actor=actor)
    initialize_approval_chain(ride)
    return ride


@transaction.atomic
def initialize_approval_chain(ride: Ride):
    ride.approval_steps.all().delete()
    chain = approval_chain_for_policy()
    # Shuttle / organizer-created rides without a requester skip manager stage
    if not ride.requester_id:
        chain = tuple(s for s in chain if s != ApprovalStage.MANAGER) or (ApprovalStage.TRANSPORT,)
    for i, stage in enumerate(chain, start=1):
        RideApprovalStep.objects.create(
            ride=ride,
            stage=stage,
            sequence=i,
            status=StepStatus.PENDING if i == 1 else StepStatus.WAITING,
        )
    ride.status = RideStatus.PENDING_APPROVAL
    ride.current_stage = chain[0]
    ride.save(update_fields=["status", "current_stage", "updated_at"])
    _notify_stage_actors(ride, chain[0])
    return ride


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

def user_can_act_as_manager(user, ride: Ride) -> bool:
    if user_has_permission(user, "approve_transport") or user_has_permission(user, "manage_transport"):
        return True
    if getattr(user, "is_superuser", False):
        return True
    profile = getattr(user, "employee_profile", None)
    requester = ride.requester
    if not profile or not requester:
        return False
    # Dept head or direct manager
    if requester.manager_id and requester.manager_id == profile.pk:
        return True
    if requester.department_id and requester.department.head_id == profile.pk:
        return True
    role = getattr(user, "role", None)
    return bool(role and role.name in {"Department Manager", "Department Head", "Supervisor", "HR Manager", "Admin"})


def user_can_act_as_transport(user) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return user_has_permission(user, "approve_transport") or user_has_permission(user, "manage_transport")


def user_can_review_ride(user, ride: Ride) -> bool:
    if ride.status != RideStatus.PENDING_APPROVAL:
        return False
    step = ride.approval_steps.filter(status=StepStatus.PENDING).first()
    if not step:
        return False
    if step.stage == ApprovalStage.MANAGER:
        return user_can_act_as_manager(user, ride)
    if step.stage == ApprovalStage.TRANSPORT:
        return user_can_act_as_transport(user)
    return False


def pending_approvals_for_user(user):
    qs = Ride.objects.filter(status=RideStatus.PENDING_APPROVAL).select_related(
        "vehicle", "driver", "requester__user", "organizer",
    ).prefetch_related("approval_steps", "passengers")
    return [r for r in qs if user_can_review_ride(user, r)]


@transaction.atomic
def process_approval(ride: Ride, user, decision: str, note: str = ""):
    if not user_can_review_ride(user, ride):
        raise PermissionError("You cannot review this ride at the current stage.")
    step = ride.approval_steps.filter(status=StepStatus.PENDING).select_for_update().first()
    if not step:
        raise ValueError("No pending approval step.")

    if decision == "reject":
        step.reject(user, note)
        ride.approval_steps.filter(status=StepStatus.WAITING).update(status=StepStatus.SKIPPED)
        ride.status = RideStatus.REJECTED
        ride.current_stage = ""
        ride.save(update_fields=["status", "current_stage", "updated_at"])
        record_event(ride, RideEventType.REJECTED, f"Rejected: {note or 'No reason'}", actor=user)
        if ride.requester and ride.requester.user_id:
            deliver_notification(
                ride.requester.user,
                "Ride rejected",
                f"Your ride {ride.reference} was rejected. {note}".strip(),
                category="approval",
                link=f"/transport/rides/{ride.pk}/",
                channels=["email"] if ride.requester.user.email else [],
            )
        return ride

    step.approve(user, note)
    record_event(ride, RideEventType.APPROVED, f"Approved at {step.get_stage_display()} stage", actor=user)
    nxt = ride.approval_steps.filter(status=StepStatus.WAITING).order_by("sequence").first()
    if nxt:
        nxt.mark_pending()
        ride.current_stage = nxt.stage
        ride.save(update_fields=["current_stage", "updated_at"])
        _notify_stage_actors(ride, nxt.stage)
        return ride

    # Fully approved
    ride.status = RideStatus.APPROVED
    ride.current_stage = ""
    ride.save(update_fields=["status", "current_stage", "updated_at"])
    for p in ride.passengers.filter(status=PassengerStatus.REQUESTED):
        p.status = PassengerStatus.CONFIRMED
        p.save(update_fields=["status", "updated_at"])
    refresh_seats_reserved(ride)

    policy = TransportationPolicy.current()
    if policy.require_driver_acceptance and ride.driver_id:
        ride.status = RideStatus.DRIVER_PENDING
        ride.save(update_fields=["status", "updated_at"])
        record_event(ride, RideEventType.DRIVER_ASSIGNED, "Awaiting driver acceptance", actor=user)
        _notify_driver(ride)
    else:
        ride.status = RideStatus.READY
        ride.save(update_fields=["status", "updated_at"])
        record_event(ride, RideEventType.READY, "Ride ready (no driver acceptance required)", actor=user)

    if ride.requester and ride.requester.user_id:
        deliver_notification(
            ride.requester.user,
            "Ride approved",
            f"Your ride {ride.reference} has been approved.",
            category="approval",
            link=f"/transport/rides/{ride.pk}/",
            channels=["email"] if ride.requester.user.email else [],
        )
    return ride


def _notify_stage_actors(ride, stage):
    from apps.accounts.models import User

    if stage == ApprovalStage.TRANSPORT:
        users = User.objects.filter(
            Q(is_superuser=True) | Q(role__permissions__codename__in=["approve_transport", "manage_transport"])
        ).distinct()[:15]
    else:
        users = []
        if ride.requester and ride.requester.manager_id:
            mgr = ride.requester.manager
            if mgr and mgr.user_id:
                users = [mgr.user]
        if not users and ride.requester and ride.requester.department and ride.requester.department.head_id:
            head = ride.requester.department.head
            if head and head.user_id:
                users = [head.user]
    for u in users:
        deliver_notification(
            u,
            "Transport ride awaiting approval",
            f"{ride.reference}: {ride.origin_label} — {ride.scheduled_departure:%d %b %H:%M}",
            category="approval",
            link="/transport/approvals/",
            channels=["email"] if u.email else [],
        )


def _notify_driver(ride: Ride):
    if not ride.driver_id:
        return
    user = ride.driver.employee.user
    deliver_notification(
        user,
        "New transportation assignment",
        f"{ride.reference}: {ride.origin_label} at {ride.scheduled_departure:%d %b %H:%M}",
        category="task",
        link="/transport/driver/",
        channels=["email"] if user.email else [],
    )


# ---------------------------------------------------------------------------
# Driver actions
# ---------------------------------------------------------------------------

@transaction.atomic
def driver_accept(ride: Ride, user):
    if ride.status != RideStatus.DRIVER_PENDING:
        raise ValueError("Ride is not awaiting driver acceptance.")
    if not ride.driver_id or ride.driver.employee.user_id != user.id:
        if not user_has_permission(user, "manage_transport") and not getattr(user, "is_superuser", False):
            raise PermissionError("Only the assigned driver can accept.")
    ride.status = RideStatus.DRIVER_ACCEPTED
    ride.save(update_fields=["status", "updated_at"])
    record_event(ride, RideEventType.DRIVER_ACCEPTED, "Driver accepted assignment", actor=user)
    ride.status = RideStatus.READY
    ride.save(update_fields=["status", "updated_at"])
    record_event(ride, RideEventType.READY, "Ride marked ready", actor=user)
    if ride.requester and ride.requester.user_id:
        deliver_notification(
            ride.requester.user,
            "Driver assigned",
            f"Driver accepted {ride.reference}. Your ride is ready.",
            category="task",
            link=f"/transport/rides/{ride.pk}/",
            channels=["email"] if ride.requester.user.email else [],
        )
    return ride


@transaction.atomic
def driver_decline(ride: Ride, user, note=""):
    if ride.status != RideStatus.DRIVER_PENDING:
        raise ValueError("Ride is not awaiting driver acceptance.")
    ride.status = RideStatus.APPROVED
    ride.driver = None
    ride.save(update_fields=["status", "driver", "updated_at"])
    record_event(
        ride, RideEventType.DRIVER_DECLINED,
        f"Driver declined: {note or 'No reason'}",
        actor=user,
    )
    return ride


@transaction.atomic
def start_journey(ride: Ride, user, lat=None, lng=None):
    if ride.status not in (RideStatus.READY, RideStatus.DRIVER_ACCEPTED):
        raise ValueError("Ride must be ready before starting.")
    if not ride.can_transition_to(RideStatus.IN_PROGRESS):
        raise ValueError("Invalid status transition.")
    now = timezone.now()
    ride.status = RideStatus.IN_PROGRESS
    ride.actual_start_at = now
    ride.save(update_fields=["status", "actual_start_at", "updated_at"])
    if ride.vehicle_id:
        Vehicle.objects.filter(pk=ride.vehicle_id).update(status=VehicleStatus.IN_USE)
    # Passengers enter boarding; driver marks onboard individually.
    for p in ride.passengers.filter(status=PassengerStatus.CONFIRMED):
        p.status = PassengerStatus.BOARDING
        p.save(update_fields=["status", "updated_at"])
    record_event(
        ride, RideEventType.STARTED, "Journey started",
        actor=user, lat=lat, lng=lng,
    )
    for p in ride.passengers.select_related("employee__user"):
        if p.employee.user_id:
            deliver_notification(
                p.employee.user,
                "Your ride has started",
                f"{ride.reference} is now in progress. Track live: /transport/rides/{ride.pk}/journey/",
                category="task",
                link=f"/transport/rides/{ride.pk}/journey/",
            )
    return ride


def _user_can_board_passenger(user, ride: Ride) -> bool:
    if user_has_permission(user, "manage_transport") or getattr(user, "is_superuser", False):
        return True
    emp = getattr(user, "employee_profile", None)
    if not emp:
        return False
    driver = getattr(emp, "driver_profile", None)
    return bool(driver and ride.driver_id == driver.id)


@transaction.atomic
def mark_passenger_boarding(ride: Ride, passenger: RidePassenger, user):
    if ride.status not in (RideStatus.READY, RideStatus.DRIVER_ACCEPTED, RideStatus.IN_PROGRESS):
        raise ValueError("Ride is not open for boarding.")
    if passenger.ride_id != ride.id:
        raise ValueError("Passenger does not belong to this ride.")
    if not _user_can_board_passenger(user, ride):
        raise PermissionError("Only the assigned driver or transport admin can mark boarding.")
    if passenger.status not in (PassengerStatus.CONFIRMED, PassengerStatus.BOARDING):
        raise ValueError(f"Cannot mark boarding from status {passenger.status}.")
    passenger.status = PassengerStatus.BOARDING
    passenger.save(update_fields=["status", "updated_at"])
    record_event(
        ride, RideEventType.NOTE,
        f"{passenger.employee} boarding",
        actor=user, passenger=passenger,
    )
    return passenger


@transaction.atomic
def mark_passenger_onboard(ride: Ride, passenger: RidePassenger, user):
    if ride.status not in (RideStatus.READY, RideStatus.DRIVER_ACCEPTED, RideStatus.IN_PROGRESS):
        raise ValueError("Ride is not open for boarding.")
    if passenger.ride_id != ride.id:
        raise ValueError("Passenger does not belong to this ride.")
    if not _user_can_board_passenger(user, ride):
        raise PermissionError("Only the assigned driver or transport admin can mark onboard.")
    if passenger.status not in (
        PassengerStatus.CONFIRMED, PassengerStatus.BOARDING, PassengerStatus.ONBOARD,
    ):
        raise ValueError(f"Cannot mark onboard from status {passenger.status}.")
    now = timezone.now()
    passenger.status = PassengerStatus.ONBOARD
    passenger.boarded_at = passenger.boarded_at or now
    passenger.save(update_fields=["status", "boarded_at", "updated_at"])
    record_event(
        ride, RideEventType.NOTE,
        f"{passenger.employee} onboard",
        actor=user, passenger=passenger,
    )
    return passenger


@transaction.atomic
def mark_passenger_arrived(ride: Ride, passenger: RidePassenger, user, lat=None, lng=None):
    if ride.status != RideStatus.IN_PROGRESS:
        raise ValueError("Ride is not in progress.")
    if passenger.ride_id != ride.id:
        raise ValueError("Passenger does not belong to this ride.")
    now = timezone.now()
    passenger.status = PassengerStatus.ARRIVED
    passenger.arrived_at = now
    passenger.arrival_lat = lat
    passenger.arrival_lng = lng
    passenger.save(update_fields=["status", "arrived_at", "arrival_lat", "arrival_lng", "updated_at"])
    if passenger.stop_id:
        stop = passenger.stop
        remaining = stop.passengers.exclude(status=PassengerStatus.ARRIVED).exclude(pk=passenger.pk)
        if not remaining.exists():
            stop.is_completed = True
            stop.actual_arrival = now
            stop.save(update_fields=["is_completed", "actual_arrival"])
            record_event(
                ride, RideEventType.STOP_ARRIVED,
                f"Stop completed: {stop.label}",
                actor=user, stop=stop,
            )
    record_event(
        ride, RideEventType.PASSENGER_ARRIVED,
        f"{passenger.employee} arrived at {passenger.destination_label}",
        actor=user, passenger=passenger, lat=lat, lng=lng,
    )
    if passenger.employee.user_id:
        deliver_notification(
            passenger.employee.user,
            "You have arrived",
            f"{ride.reference}: arrived at {passenger.destination_label}.",
            category="task",
            link=f"/transport/rides/{ride.pk}/",
        )
    # Auto-complete ride when all passengers arrived
    open_pax = ride.passengers.exclude(
        status__in=[PassengerStatus.ARRIVED, PassengerStatus.CANCELLED, PassengerStatus.NO_SHOW, PassengerStatus.REJECTED]
    )
    if not open_pax.exists():
        complete_ride(ride, user)
    return passenger


@transaction.atomic
def complete_ride(ride: Ride, user):
    if ride.status not in (RideStatus.IN_PROGRESS, RideStatus.READY):
        if ride.status == RideStatus.COMPLETED:
            return ride
        raise ValueError("Ride cannot be completed from current status.")
    ride.status = RideStatus.COMPLETED
    ride.actual_end_at = timezone.now()
    ride.save(update_fields=["status", "actual_end_at", "updated_at"])
    if ride.vehicle_id:
        Vehicle.objects.filter(pk=ride.vehicle_id).update(status=VehicleStatus.AVAILABLE)
    record_event(ride, RideEventType.COMPLETED, "Ride completed", actor=user)
    return ride


def user_can_cancel_ride(user, ride: Ride) -> bool:
    if user_has_permission(user, "manage_transport") or getattr(user, "is_superuser", False):
        return True
    if ride.organizer_id == user.id:
        return True
    emp = getattr(user, "employee_profile", None)
    if emp and ride.requester_id == emp.id:
        return True
    return False


@transaction.atomic
def cancel_ride(ride: Ride, user, reason=""):
    if ride.status in (RideStatus.COMPLETED, RideStatus.CANCELLED, RideStatus.ABORTED):
        raise ValueError("Ride is already closed.")
    if ride.status == RideStatus.IN_PROGRESS:
        raise ValueError(
            "In-progress rides cannot be cancelled. Complete the journey or ask a transport admin."
        )
    if not user_can_cancel_ride(user, ride):
        raise PermissionError("You cannot cancel this ride.")

    policy = TransportationPolicy.current()
    reason = (reason or "").strip()
    post_draft = ride.status not in (RideStatus.DRAFT, RideStatus.SUBMITTED)
    if policy.require_cancel_reason_after_approval and post_draft and not reason:
        raise ValueError("A cancellation reason is required after the ride has been submitted/approved.")

    ride.status = RideStatus.CANCELLED
    ride.cancellation_reason = reason[:255]
    ride.save(update_fields=["status", "cancellation_reason", "updated_at"])
    ride.passengers.exclude(
        status__in=[PassengerStatus.ARRIVED, PassengerStatus.CANCELLED]
    ).update(status=PassengerStatus.CANCELLED)
    refresh_seats_reserved(ride)
    if ride.vehicle_id:
        Vehicle.objects.filter(pk=ride.vehicle_id, status=VehicleStatus.IN_USE).update(
            status=VehicleStatus.AVAILABLE
        )
    record_event(ride, RideEventType.CANCELLED, f"Cancelled: {reason or 'No reason'}", actor=user)

    recipients = set()
    if ride.requester_id and ride.requester.user_id:
        recipients.add(ride.requester.user)
    if ride.organizer_id:
        recipients.add(ride.organizer)
    for p in ride.passengers.select_related("employee__user"):
        if p.employee.user_id:
            recipients.add(p.employee.user)
    if ride.driver_id and ride.driver.employee.user_id:
        recipients.add(ride.driver.employee.user)
    for u in recipients:
        if u.id == getattr(user, "id", None):
            continue
        deliver_notification(
            u,
            "Ride cancelled",
            f"{ride.reference} was cancelled. {reason}".strip(),
            category="task",
            link=f"/transport/rides/{ride.pk}/",
            channels=["email"] if u.email else [],
        )
    return ride


@transaction.atomic
def passenger_leave_ride(ride: Ride, employee, user, reason=""):
    """Passenger drops their seat before the journey starts (not during IN_PROGRESS)."""
    if ride.status == RideStatus.IN_PROGRESS:
        raise ValueError(
            "You cannot leave an in-progress journey from self-service. "
            "Contact transport admin or the driver."
        )
    if ride.status in (RideStatus.COMPLETED, RideStatus.CANCELLED, RideStatus.ABORTED):
        raise ValueError("Ride is already closed.")
    passenger = ride.passengers.filter(employee=employee).exclude(
        status__in=[PassengerStatus.CANCELLED, PassengerStatus.ARRIVED, PassengerStatus.REJECTED]
    ).first()
    if not passenger:
        raise ValueError("You are not an active passenger on this ride.")
    is_self = employee.user_id == user.id
    is_admin = user_has_permission(user, "manage_transport") or getattr(user, "is_superuser", False)
    if not is_self and not is_admin:
        raise PermissionError("Only the passenger or a transport admin can remove this seat.")
    passenger.status = PassengerStatus.CANCELLED
    passenger.notes = (reason or passenger.notes or "")[:255]
    passenger.save(update_fields=["status", "notes", "updated_at"])
    refresh_seats_reserved(ride)
    record_event(
        ride, RideEventType.PASSENGER_REMOVED,
        f"{employee} left the ride" + (f": {reason}" if reason else ""),
        actor=user, passenger=passenger,
    )
    if ride.organizer_id and ride.organizer_id != user.id:
        deliver_notification(
            ride.organizer,
            "Passenger left ride",
            f"{employee} left {ride.reference}.",
            category="task",
            link=f"/transport/rides/{ride.pk}/",
        )
    return passenger


# ---------------------------------------------------------------------------
# Carpool join + route deviation
# ---------------------------------------------------------------------------

def _ride_route_points(ride: Ride) -> list[GeoPoint]:
    points = []
    if ride.origin_lat is not None and ride.origin_lng is not None:
        points.append(GeoPoint(float(ride.origin_lat), float(ride.origin_lng), ride.origin_label or "Origin"))
    for stop in ride.stops.order_by("sequence"):
        if stop.lat is not None and stop.lng is not None:
            points.append(GeoPoint(float(stop.lat), float(stop.lng), stop.label or "Stop"))
    return points


def carpool_route_deviation(
    ride: Ride,
    destination_lat,
    destination_lng,
    *,
    policy: TransportationPolicy | None = None,
) -> dict:
    """
    Compare current route distance vs route with the join destination appended.
    Uses OSRM when available, else haversine. Returns percent increase and allow flag.
    """
    policy = policy or TransportationPolicy.current()
    max_pct = int(policy.max_route_deviation_percent or 0)
    result = {
        "checked": False,
        "deviation_percent": None,
        "base_km": None,
        "new_km": None,
        "max_percent": max_pct,
        "allowed": True,
        "provider": "",
    }
    if destination_lat is None or destination_lng is None:
        return result
    try:
        dest_lat = float(destination_lat)
        dest_lng = float(destination_lng)
    except (TypeError, ValueError):
        return result

    base_points = _ride_route_points(ride)
    if len(base_points) < 1:
        return result

    # Baseline: existing multi-stop route, or origin→first passenger dest if no stops yet
    if len(base_points) == 1:
        # Use furthest confirmed passenger destination as current end when no stops
        end_lat = end_lng = None
        for pax in ride.passengers.filter(
            status__in=[
                PassengerStatus.CONFIRMED, PassengerStatus.BOARDING,
                PassengerStatus.ONBOARD, PassengerStatus.REQUESTED,
            ]
        ):
            if pax.destination_lat is not None and pax.destination_lng is not None:
                end_lat, end_lng = float(pax.destination_lat), float(pax.destination_lng)
                break
        if end_lat is None:
            # Nothing to compare against yet — treat join as establishing the route
            result["checked"] = True
            result["deviation_percent"] = 0.0
            result["allowed"] = True
            return result
        base_points = base_points + [GeoPoint(end_lat, end_lng, "Current end")]

    new_points = base_points + [GeoPoint(dest_lat, dest_lng, "Join destination")]
    base_route = estimate_route_or_fallback(base_points)
    new_route = estimate_route_or_fallback(new_points)
    base_km = float(base_route.distance_km or 0)
    new_km = float(new_route.distance_km or 0)
    if base_km <= 0:
        deviation = 0.0 if new_km <= 0 else 100.0
    else:
        deviation = max(0.0, round(((new_km - base_km) / base_km) * 100.0, 1))

    result.update({
        "checked": True,
        "deviation_percent": deviation,
        "base_km": round(base_km, 2),
        "new_km": round(new_km, 2),
        "provider": new_route.provider or base_route.provider,
        "allowed": deviation <= max_pct,
    })
    return result


@transaction.atomic
def request_to_join(ride: Ride, employee, destination_label, destination_lat=None, destination_lng=None):
    policy = TransportationPolicy.current()
    if not policy.allow_carpooling or not ride.allow_carpool:
        raise ValueError("Carpooling is not allowed on this ride.")
    if ride.status not in (
        RideStatus.APPROVED, RideStatus.DRIVER_PENDING, RideStatus.DRIVER_ACCEPTED, RideStatus.READY,
        RideStatus.PENDING_APPROVAL,
    ):
        raise ValueError("This ride is not open for join requests.")
    if ride.passengers.filter(employee=employee).exists():
        raise ValueError("You are already on this ride.")
    if JoinRequest.objects.filter(ride=ride, employee=employee, status__in=[
        JoinRequestStatus.PENDING, JoinRequestStatus.ORGANIZER_APPROVED, JoinRequestStatus.ADMIN_APPROVED,
    ]).exists():
        raise ValueError("You already have a pending join request.")
    # Capacity check (optimistic; confirmed again on dual approval)
    if ride.seats_available < 1 and ride.capacity > 0:
        raise ValueError("Vehicle capacity has been reached.")

    deviation = carpool_route_deviation(
        ride, destination_lat, destination_lng, policy=policy,
    )
    if deviation["checked"] and not deviation["allowed"]:
        raise ValueError(
            f"Destination exceeds max route deviation "
            f"({deviation['deviation_percent']}% > {deviation['max_percent']}%). "
            "Choose a closer drop-off or request a separate ride."
        )

    jr = JoinRequest.objects.create(
        ride=ride,
        employee=employee,
        destination_label=destination_label,
        destination_lat=destination_lat,
        destination_lng=destination_lng,
        status=JoinRequestStatus.PENDING,
    )
    actor = employee.user if employee.user_id else None
    msg = f"{employee} requested to join → {destination_label}"
    if deviation.get("deviation_percent") is not None:
        msg += f" (route +{deviation['deviation_percent']}%)"
    record_event(
        ride, RideEventType.JOIN_REQUESTED, msg, actor=actor,
        **({"deviation": deviation} if deviation.get("checked") else {}),
    )
    if ride.organizer_id:
        deliver_notification(
            ride.organizer,
            "Carpool join request",
            f"{employee} wants to join {ride.reference} ({destination_label}).",
            category="approval",
            link=f"/transport/rides/{ride.pk}/",
            channels=["email"] if ride.organizer.email else [],
        )
    return jr


@transaction.atomic
def decide_join_request(jr: JoinRequest, user, *, as_organizer: bool | None, approve: bool, note=""):
    """
    Dual approval: organizer and transport admin, order-independent.
    as_organizer=True → organizer decision; False → admin; None → auto-detect.
    """
    jr = JoinRequest.objects.select_for_update().select_related("ride", "employee").get(pk=jr.pk)
    ride = Ride.objects.select_for_update().get(pk=jr.ride_id)

    is_organizer = ride.organizer_id == user.id
    is_admin = user_can_act_as_transport(user)
    if as_organizer is True and not is_organizer and not getattr(user, "is_superuser", False):
        raise PermissionError("Only the ride organizer can approve as organizer.")
    if as_organizer is False and not is_admin:
        raise PermissionError("Only transport admins can approve as admin.")
    if as_organizer is None:
        if is_organizer and jr.organizer_approved is None:
            as_organizer = True
        elif is_admin:
            as_organizer = False
        else:
            raise PermissionError("You cannot decide this join request.")

    if not approve:
        if as_organizer:
            jr.organizer_approved = False
            jr.organizer_acted_by = user
        else:
            jr.admin_approved = False
            jr.admin_acted_by = user
        jr.status = JoinRequestStatus.REJECTED
        jr.note = note[:255]
        jr.save()
        return jr

    if as_organizer:
        jr.organizer_approved = True
        jr.organizer_acted_by = user
        if jr.admin_approved is True:
            jr.status = JoinRequestStatus.CONFIRMED
        elif jr.admin_approved is None:
            jr.status = JoinRequestStatus.ORGANIZER_APPROVED
    else:
        jr.admin_approved = True
        jr.admin_acted_by = user
        if jr.organizer_approved is True:
            jr.status = JoinRequestStatus.CONFIRMED
        elif jr.organizer_approved is None:
            jr.status = JoinRequestStatus.ADMIN_APPROVED
    jr.note = note[:255]
    jr.save()

    if jr.status == JoinRequestStatus.CONFIRMED:
        _confirm_join(ride, jr, user)
    return jr


@transaction.atomic
def _confirm_join(ride: Ride, jr: JoinRequest, actor):
    refresh_seats_reserved(ride)
    if ride.capacity and ride.seats_reserved >= ride.capacity:
        jr.status = JoinRequestStatus.REJECTED
        jr.note = "Vehicle capacity has been reached."
        jr.save(update_fields=["status", "note", "updated_at"])
        raise ValueError("Vehicle capacity has been reached.")

    deviation = carpool_route_deviation(ride, jr.destination_lat, jr.destination_lng)
    if deviation["checked"] and not deviation["allowed"]:
        jr.status = JoinRequestStatus.REJECTED
        jr.note = (
            f"Route deviation {deviation['deviation_percent']}% "
            f"exceeds max {deviation['max_percent']}%."
        )[:255]
        jr.save(update_fields=["status", "note", "updated_at"])
        raise ValueError(jr.note)

    # Reuse existing stop with same label or create next sequence
    stop = ride.stops.filter(label__iexact=jr.destination_label).first()
    if not stop:
        seq = (ride.stops.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
        stop = RideStop.objects.create(
            ride=ride,
            sequence=seq,
            label=jr.destination_label,
            lat=jr.destination_lat,
            lng=jr.destination_lng,
        )
    passenger = RidePassenger.objects.create(
        ride=ride,
        employee=jr.employee,
        stop=stop,
        destination_label=jr.destination_label,
        destination_lat=jr.destination_lat,
        destination_lng=jr.destination_lng,
        status=PassengerStatus.CONFIRMED,
    )
    refresh_seats_reserved(ride)
    record_event(
        ride, RideEventType.JOIN_CONFIRMED,
        f"{jr.employee} joined the ride → {jr.destination_label}",
        actor=actor, passenger=passenger,
    )
    record_event(
        ride, RideEventType.PASSENGER_ADDED,
        f"Passenger added: {jr.employee}",
        actor=actor, passenger=passenger,
    )
    if jr.employee.user_id:
        deliver_notification(
            jr.employee.user,
            "Carpool join confirmed",
            f"You are confirmed on {ride.reference}.",
            category="approval",
            link=f"/transport/rides/{ride.pk}/",
            channels=["email"] if jr.employee.user.email else [],
        )
    return passenger


# ---------------------------------------------------------------------------
# Phase 4 — GPS / geofencing (haversine, no PostGIS)
# ---------------------------------------------------------------------------

def user_can_ping_ride(user, ride: Ride) -> bool:
    """Assigned driver, or transport manager."""
    if user_has_permission(user, "manage_transport") or getattr(user, "is_superuser", False):
        return True
    emp = getattr(user, "employee_profile", None)
    if not emp:
        return False
    driver = getattr(emp, "driver_profile", None)
    return bool(driver and ride.driver_id == driver.id)


def geofence_hints(ride: Ride, lat: float, lng: float, policy: TransportationPolicy | None = None) -> dict:
    """
    Return proximity hints for origin / stops / passenger destinations.
    Manual Start/Arrived remain the fallback; optional auto_* flags may act.
    """
    policy = policy or TransportationPolicy.current()
    radius = float(policy.geofence_radius_metres or 100)
    hints = {
        "radius_m": radius,
        "near_origin": False,
        "origin_distance_m": None,
        "near_stops": [],
        "near_passengers": [],
    }
    if ride.origin_lat is not None and ride.origin_lng is not None:
        d = haversine_metres(lat, lng, float(ride.origin_lat), float(ride.origin_lng))
        hints["origin_distance_m"] = round(d, 1)
        hints["near_origin"] = d <= radius

    for stop in ride.stops.all():
        if stop.lat is None or stop.lng is None or stop.is_completed:
            continue
        d = haversine_metres(lat, lng, float(stop.lat), float(stop.lng))
        if d <= radius:
            hints["near_stops"].append({
                "stop_id": stop.id,
                "label": stop.label,
                "distance_m": round(d, 1),
            })

    for pax in ride.passengers.filter(
        status__in=[PassengerStatus.ONBOARD, PassengerStatus.BOARDING, PassengerStatus.CONFIRMED]
    ):
        plat = pax.destination_lat if pax.destination_lat is not None else (
            pax.stop.lat if pax.stop_id and pax.stop.lat is not None else None
        )
        plng = pax.destination_lng if pax.destination_lng is not None else (
            pax.stop.lng if pax.stop_id and pax.stop.lng is not None else None
        )
        if plat is None or plng is None:
            continue
        d = haversine_metres(lat, lng, float(plat), float(plng))
        if d <= radius:
            hints["near_passengers"].append({
                "passenger_id": pax.id,
                "name": str(pax.employee),
                "destination": pax.destination_label,
                "distance_m": round(d, 1),
            })
    return hints


@transaction.atomic
def record_location_ping(
    ride: Ride,
    user,
    *,
    lat: float,
    lng: float,
    speed_kmh=None,
    accuracy_m=None,
    source="driver_pwa",
    apply_auto_actions: bool = True,
) -> tuple[LocationPing, dict]:
    """
    Persist a GPS sample and optionally assist start/arrival via geofence.
    Returns (ping, payload) where payload includes hints and any auto actions taken.
    """
    if not user_can_ping_ride(user, ride):
        raise PermissionError("You cannot send location for this ride.")
    if ride.status not in (
        RideStatus.DRIVER_ACCEPTED, RideStatus.READY, RideStatus.IN_PROGRESS,
    ):
        raise ValueError("Location sharing is only available for ready or in-progress rides.")
    if not ride.vehicle_id:
        raise ValueError("Ride has no vehicle assigned.")

    policy = TransportationPolicy.current()
    ping = LocationPing.objects.create(
        ride=ride,
        vehicle_id=ride.vehicle_id,
        lat=lat,
        lng=lng,
        speed_kmh=speed_kmh,
        accuracy_m=accuracy_m,
        source=source or "driver_pwa",
        recorded_at=timezone.now(),
    )

    hints = geofence_hints(ride, lat, lng, policy)
    actions = []

    if apply_auto_actions:
        if (
            policy.auto_start_enabled
            and hints["near_origin"]
            and ride.status in (RideStatus.READY, RideStatus.DRIVER_ACCEPTED)
        ):
            start_journey(ride, user, lat=lat, lng=lng)
            ride.refresh_from_db()
            actions.append({"type": "auto_started", "message": "Journey auto-started near origin."})

        if policy.auto_arrival_enabled and ride.status == RideStatus.IN_PROGRESS:
            for item in hints["near_passengers"]:
                passenger = RidePassenger.objects.filter(
                    pk=item["passenger_id"], ride=ride,
                ).exclude(status=PassengerStatus.ARRIVED).first()
                if not passenger:
                    continue
                mark_passenger_arrived(ride, passenger, user, lat=lat, lng=lng)
                actions.append({
                    "type": "auto_arrived",
                    "passenger_id": passenger.id,
                    "message": f"Marked arrived near {passenger.destination_label}.",
                })
            ride.refresh_from_db()

    return ping, {
        "ping_id": ping.id,
        "recorded_at": ping.recorded_at.isoformat(),
        "ride_status": ride.status,
        "hints": hints,
        "actions": actions,
        "policy": {
            "geofence_radius_metres": policy.geofence_radius_metres,
            "auto_start_enabled": policy.auto_start_enabled,
            "auto_arrival_enabled": policy.auto_arrival_enabled,
        },
    }


def serialize_live_ride(ride: Ride, last_ping: LocationPing | None = None) -> dict:
    """Latest ping + route geometry for live map markers."""
    if last_ping is None:
        last_ping = LocationPing.objects.filter(ride=ride).order_by("-recorded_at").first()

    driver_name = ""
    if ride.driver_id and ride.driver and ride.driver.employee_id:
        driver_name = getattr(ride.driver.employee, "full_name", "") or str(ride.driver.employee)

    payload = {
        "ride_id": ride.id,
        "reference": ride.reference,
        "status": ride.status,
        "status_display": ride.get_status_display(),
        "vehicle": ride.vehicle.registration_number if ride.vehicle_id else "",
        "vehicle_name": ride.vehicle.name if ride.vehicle_id else "",
        "driver": driver_name,
        "origin_label": ride.origin_label,
        "origin": (
            {"lat": float(ride.origin_lat), "lng": float(ride.origin_lng)}
            if ride.origin_lat is not None and ride.origin_lng is not None else None
        ),
        "route_geometry": ride.route_geometry or {},
        "last_ping": None,
        "detail_url": f"/transport/rides/{ride.id}/",
    }
    if last_ping:
        payload["last_ping"] = {
            "lat": float(last_ping.lat),
            "lng": float(last_ping.lng),
            "recorded_at": last_ping.recorded_at.isoformat(),
            "speed_kmh": float(last_ping.speed_kmh) if last_ping.speed_kmh is not None else None,
            "accuracy_m": float(last_ping.accuracy_m) if last_ping.accuracy_m is not None else None,
            "source": last_ping.source,
        }
    return payload


def active_rides_for_live_map():
    """IN_PROGRESS rides for the ops live map."""
    return (
        Ride.objects.filter(status=RideStatus.IN_PROGRESS)
        .select_related("vehicle", "driver__employee__user")
        .order_by("-actual_start_at", "-scheduled_departure")
    )


def live_map_payload():
    rides = list(active_rides_for_live_map())
    if not rides:
        return []
    ride_ids = [r.id for r in rides]
    # One latest ping per ride without Prefetch slice quirks
    latest_by_ride = {}
    for ping in LocationPing.objects.filter(ride_id__in=ride_ids).order_by("ride_id", "-recorded_at"):
        if ping.ride_id not in latest_by_ride:
            latest_by_ride[ping.ride_id] = ping
    return [serialize_live_ride(r, latest_by_ride.get(r.id)) for r in rides]


# ---------------------------------------------------------------------------
# Phase 5 — Fleet due reminders (documents + maintenance)
# ---------------------------------------------------------------------------

FLEET_DUE_SOON_DAYS = 30
FLEET_DUE_SOON_KM = 500


def _vehicle_latest_odometer(vehicle_id: int) -> int | None:
    from .models import FuelEntry, MaintenanceRecord

    readings = []
    fuel_km = (
        FuelEntry.objects.filter(vehicle_id=vehicle_id, odometer_km__isnull=False)
        .order_by("-date", "-created_at")
        .values_list("odometer_km", flat=True)
        .first()
    )
    if fuel_km is not None:
        readings.append(fuel_km)
    maint_km = (
        MaintenanceRecord.objects.filter(vehicle_id=vehicle_id, odometer_km__isnull=False)
        .order_by("-performed_on", "-created_at")
        .values_list("odometer_km", flat=True)
        .first()
    )
    if maint_km is not None:
        readings.append(maint_km)
    return max(readings) if readings else None


def fleet_due_items(*, within_days: int = FLEET_DUE_SOON_DAYS, within_km: int = FLEET_DUE_SOON_KM):
    """
    Collect document expiry and maintenance next-due items that are overdue or due soon.
    Returns list of dicts sorted overdue first, then by soonest date / km.
    """
    from datetime import date as date_cls

    from .models import MaintenanceRecord, VehicleDocument

    today = timezone.localdate()
    horizon = today + timedelta(days=within_days)
    items = []

    docs = (
        VehicleDocument.objects.filter(expires_on__isnull=False)
        .select_related("vehicle")
        .filter(vehicle__is_active=True)
    )
    for doc in docs:
        exp = doc.expires_on
        if exp > horizon:
            continue
        status = "overdue" if exp < today else "due_soon"
        items.append({
            "kind": "document",
            "status": status,
            "vehicle": doc.vehicle,
            "vehicle_id": doc.vehicle_id,
            "label": f"{doc.get_document_type_display()}: {doc.title}",
            "due_date": exp,
            "due_km": None,
            "sort_date": exp,
            "sort_km": None,
        })

    records = (
        MaintenanceRecord.objects.filter(
            Q(next_due_date__isnull=False) | Q(next_due_km__isnull=False)
        )
        .select_related("vehicle")
        .filter(vehicle__is_active=True)
    )
    odo_cache: dict[int, int | None] = {}
    for rec in records:
        vid = rec.vehicle_id
        if vid not in odo_cache:
            odo_cache[vid] = _vehicle_latest_odometer(vid)
        current_km = odo_cache[vid]

        date_status = None
        if rec.next_due_date:
            if rec.next_due_date < today:
                date_status = "overdue"
            elif rec.next_due_date <= horizon:
                date_status = "due_soon"

        km_status = None
        if rec.next_due_km is not None and current_km is not None:
            remaining = rec.next_due_km - current_km
            if remaining <= 0:
                km_status = "overdue"
            elif remaining <= within_km:
                km_status = "due_soon"

        if not date_status and not km_status:
            continue

        status = "overdue" if "overdue" in {date_status, km_status} else "due_soon"
        items.append({
            "kind": "maintenance",
            "status": status,
            "vehicle": rec.vehicle,
            "vehicle_id": vid,
            "label": rec.title or rec.get_maintenance_type_display(),
            "due_date": rec.next_due_date,
            "due_km": rec.next_due_km,
            "sort_date": rec.next_due_date or date_cls.max,
            "sort_km": rec.next_due_km,
        })

    def _sort_key(item):
        overdue_rank = 0 if item["status"] == "overdue" else 1
        d = item["sort_date"] or date_cls.max
        return (overdue_rank, d, item.get("sort_km") or 10**12)

    items.sort(key=_sort_key)
    return items


def vehicle_due_chips(vehicle, *, within_days: int = FLEET_DUE_SOON_DAYS, within_km: int = FLEET_DUE_SOON_KM):
    """Compact chip labels for a single vehicle (list/detail)."""
    chips = []
    for item in fleet_due_items(within_days=within_days, within_km=within_km):
        if item["vehicle_id"] != vehicle.pk:
            continue
        prefix = "Overdue" if item["status"] == "overdue" else "Due soon"
        if item["kind"] == "document":
            chips.append({"text": f"{prefix}: {item['label']}", "status": item["status"]})
        else:
            parts = [f"{prefix}: {item['label']}"]
            if item["due_date"]:
                parts.append(item["due_date"].strftime("%b %d"))
            if item["due_km"]:
                parts.append(f"{item['due_km']} km")
            chips.append({"text": " · ".join(parts), "status": item["status"]})
    return chips


# ---------------------------------------------------------------------------
# Phase 6 — Analytics
# ---------------------------------------------------------------------------

def resolve_analytics_range(range_key: str, date_from=None, date_to=None):
    """Return (start_date, end_date, range_key) for analytics filters."""
    today = timezone.localdate()
    key = (range_key or "this_month").strip().lower()
    if key == "last_30":
        return today - timedelta(days=29), today, "last_30"
    if key == "custom":
        start = date_from or (today.replace(day=1))
        end = date_to or today
        if start > end:
            start, end = end, start
        return start, end, "custom"
    # this_month
    start = today.replace(day=1)
    return start, today, "this_month"


def transport_analytics(start_date, end_date) -> dict:
    """Aggregate ride / fuel / fleet stats for the inclusive date range."""
    from calendar import month_abbr
    from decimal import Decimal

    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth

    from .models import FuelEntry, JoinRequest, MaintenanceRecord, RidePassenger

    rides = Ride.objects.filter(
        scheduled_departure__date__gte=start_date,
        scheduled_departure__date__lte=end_date,
    )
    total_trips = rides.count()
    completed = rides.filter(status=RideStatus.COMPLETED).count()
    cancelled = rides.filter(
        status__in=[RideStatus.CANCELLED, RideStatus.ABORTED, RideStatus.REJECTED]
    ).count()
    completed_rate = round((completed / total_trips) * 100, 1) if total_trips else 0.0
    cancelled_rate = round((cancelled / total_trips) * 100, 1) if total_trips else 0.0

    passengers = RidePassenger.objects.filter(
        ride__scheduled_departure__date__gte=start_date,
        ride__scheduled_departure__date__lte=end_date,
    ).exclude(
        status__in=[PassengerStatus.CANCELLED, PassengerStatus.REJECTED],
    ).count()

    distance = rides.aggregate(total=Sum("estimated_distance_km"))["total"] or Decimal("0")

    fuel_cost = (
        FuelEntry.objects.filter(date__gte=start_date, date__lte=end_date)
        .aggregate(total=Sum("total"))["total"]
        or Decimal("0")
    )
    fuel_litres = (
        FuelEntry.objects.filter(date__gte=start_date, date__lte=end_date)
        .aggregate(total=Sum("litres"))["total"]
        or Decimal("0")
    )
    maintenance_cost = (
        MaintenanceRecord.objects.filter(
            performed_on__gte=start_date, performed_on__lte=end_date,
        )
        .aggregate(total=Sum("cost"))["total"]
        or Decimal("0")
    )
    policy = TransportationPolicy.current()
    cost_per_km = Decimal(str(policy.estimated_cost_per_km or 0))
    estimated_trip_cost = (distance * cost_per_km).quantize(Decimal("0.01")) if cost_per_km else Decimal("0")
    total_ops_cost = fuel_cost + maintenance_cost

    carpool_joins = JoinRequest.objects.filter(
        status=JoinRequestStatus.CONFIRMED,
        updated_at__date__gte=start_date,
        updated_at__date__lte=end_date,
    ).count()

    active_vehicles = Vehicle.objects.filter(is_active=True).exclude(
        status=VehicleStatus.RETIRED
    ).count()

    # Trips by month (within range)
    month_rows = (
        rides.annotate(month=TruncMonth("scheduled_departure"))
        .values("month")
        .annotate(c=Count("id"))
        .order_by("month")
    )
    month_labels = []
    month_counts = []
    for row in month_rows:
        m = row["month"]
        if m:
            month_labels.append(f"{month_abbr[m.month]} {m.year}")
            month_counts.append(row["c"])

    status_rows = rides.values("status").annotate(c=Count("id")).order_by("-c")
    status_labels = []
    status_counts = []
    status_map = dict(RideStatus.choices)
    for row in status_rows:
        status_labels.append(status_map.get(row["status"], row["status"]))
        status_counts.append(row["c"])

    return {
        "total_trips": total_trips,
        "total_passengers": passengers,
        "completed": completed,
        "cancelled": cancelled,
        "completed_rate": completed_rate,
        "cancelled_rate": cancelled_rate,
        "total_distance_km": float(distance),
        "active_vehicles": active_vehicles,
        "fuel_cost": float(fuel_cost),
        "fuel_litres": float(fuel_litres),
        "maintenance_cost": float(maintenance_cost),
        "estimated_trip_cost": float(estimated_trip_cost),
        "cost_per_km": float(cost_per_km),
        "total_ops_cost": float(total_ops_cost),
        "carpool_joins": carpool_joins,
        "month_labels": month_labels,
        "month_counts": month_counts,
        "status_labels": status_labels,
        "status_counts": status_counts,
    }


def schedule_calendar_events(start=None, end=None, vehicle_id=None) -> list[dict]:
    """FullCalendar-compatible events for fleet schedule."""
    qs = Ride.objects.exclude(
        status__in=[RideStatus.CANCELLED, RideStatus.REJECTED, RideStatus.DRAFT],
    ).select_related("vehicle", "driver__employee__user")
    if vehicle_id:
        qs = qs.filter(vehicle_id=vehicle_id)
    if start:
        qs = qs.filter(scheduled_departure__date__gte=start)
    if end:
        qs = qs.filter(scheduled_departure__date__lte=end)
    qs = qs.order_by("scheduled_departure")[:500]
    color_by_status = {
        RideStatus.IN_PROGRESS: "#ea580c",
        RideStatus.COMPLETED: "#0f766e",
        RideStatus.READY: "#2563eb",
        RideStatus.DRIVER_PENDING: "#7c3aed",
        RideStatus.PENDING_APPROVAL: "#a16207",
        RideStatus.APPROVED: "#0891b2",
    }
    events = []
    for r in qs:
        end_at = r.scheduled_return or (r.scheduled_departure + timedelta(hours=2))
        title = f"{r.vehicle.registration_number if r.vehicle_id else '—'} · {r.reference}"
        events.append({
            "id": r.id,
            "title": title,
            "start": r.scheduled_departure.isoformat(),
            "end": end_at.isoformat(),
            "url": f"/transport/rides/{r.pk}/",
            "backgroundColor": color_by_status.get(r.status, "#334155"),
            "borderColor": color_by_status.get(r.status, "#334155"),
            "extendedProps": {
                "status": r.status,
                "vehicle": r.vehicle.name if r.vehicle_id else "",
                "origin": r.origin_label,
            },
        })
    return events


def passenger_journey_payload(ride: Ride) -> dict:
    """Latest position + route for passenger-facing journey view."""
    latest = (
        LocationPing.objects.filter(ride=ride)
        .order_by("-recorded_at")
        .first()
    )
    return {
        "ride_id": ride.id,
        "reference": ride.reference,
        "status": ride.status,
        "status_display": ride.get_status_display(),
        "origin_label": ride.origin_label,
        "origin_lat": float(ride.origin_lat) if ride.origin_lat is not None else None,
        "origin_lng": float(ride.origin_lng) if ride.origin_lng is not None else None,
        "route_geometry": ride.route_geometry or {},
        "latest": {
            "lat": float(latest.lat),
            "lng": float(latest.lng),
            "recorded_at": latest.recorded_at.isoformat(),
            "speed_kmh": float(latest.speed_kmh) if latest.speed_kmh is not None else None,
        } if latest else None,
        "stops": [
            {
                "label": s.label,
                "lat": float(s.lat) if s.lat is not None else None,
                "lng": float(s.lng) if s.lng is not None else None,
                "is_completed": s.is_completed,
            }
            for s in ride.stops.all()
        ],
    }

