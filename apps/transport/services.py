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
    PassengerStatus,
    Ride,
    RideApprovalStep,
    RideEvent,
    RideEventType,
    RidePassenger,
    RideStatus,
    RideStop,
    StepStatus,
    TransportationPolicy,
    Vehicle,
    VehicleStatus,
)


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


def record_event(ride, event_type, message, actor=None, passenger=None, stop=None, **meta):
    return RideEvent.objects.create(
        ride=ride,
        event_type=event_type,
        message=message[:255],
        actor=actor,
        passenger=passenger,
        stop=stop,
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
        allow_carpool=allow_carpool and policy.allow_carpooling,
    )
    stop = RideStop.objects.create(
        ride=ride,
        sequence=1,
        label=destination_label,
        lat=destination_lat,
        lng=destination_lng,
    )
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
    for p in ride.passengers.filter(status=PassengerStatus.CONFIRMED):
        p.status = PassengerStatus.ONBOARD
        p.boarded_at = now
        p.save(update_fields=["status", "boarded_at", "updated_at"])
    record_event(
        ride, RideEventType.STARTED, "Journey started",
        actor=user, lat=lat, lng=lng,
    )
    for p in ride.passengers.select_related("employee__user"):
        if p.employee.user_id:
            deliver_notification(
                p.employee.user,
                "Your ride has started",
                f"{ride.reference} is now in progress.",
                category="task",
                link=f"/transport/rides/{ride.pk}/",
            )
    return ride


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


@transaction.atomic
def cancel_ride(ride: Ride, user, reason=""):
    if ride.status in (RideStatus.COMPLETED, RideStatus.CANCELLED, RideStatus.ABORTED):
        raise ValueError("Ride is already closed.")
    if ride.status == RideStatus.IN_PROGRESS:
        raise ValueError("In-progress rides must be aborted or completed, not cancelled.")
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
    return ride


# ---------------------------------------------------------------------------
# Carpool join
# ---------------------------------------------------------------------------

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

    jr = JoinRequest.objects.create(
        ride=ride,
        employee=employee,
        destination_label=destination_label,
        destination_lat=destination_lat,
        destination_lng=destination_lng,
        status=JoinRequestStatus.PENDING,
    )
    record_event(
        ride, RideEventType.JOIN_REQUESTED,
        f"{employee} requested to join → {destination_label}",
        actor=employee.user if employee.user_id else None,
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
