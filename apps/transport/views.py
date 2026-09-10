from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from apps.core.permissions import permission_required, user_has_permission

from .forms import (
    CancelRideForm,
    DriverForm,
    FuelEntryForm,
    JoinRequestForm,
    MaintenanceRecordForm,
    ReviewForm,
    RideRequestForm,
    ShuttleRideForm,
    TransportationPolicyForm,
    VehicleDocumentForm,
    VehicleForm,
    make_shuttle_passenger_formset,
)
from .models import (
    Driver,
    FuelEntry,
    JoinRequest,
    JoinRequestStatus,
    MaintenanceRecord,
    Ride,
    RideApprovalStep,
    RideEvent,
    RideEventType,
    RidePassenger,
    RideStatus,
    RideType,
    StepStatus,
    TransportationPolicy,
    Vehicle,
)
from . import services
from .routing import GeoPoint, estimate_route_or_fallback, geocode


def _map_defaults():
    cfg = getattr(settings, "TRANSPORT_ROUTING", {})
    return {
        "map_default_lat": cfg.get("DEFAULT_LAT", 6.4584),
        "map_default_lng": cfg.get("DEFAULT_LNG", 7.5464),
        "map_default_zoom": cfg.get("DEFAULT_ZOOM", 12),
    }


def _ride_map_markers(ride):
    markers = []
    if ride.origin_lat is not None and ride.origin_lng is not None:
        markers.append({
            "lat": float(ride.origin_lat),
            "lng": float(ride.origin_lng),
            "label": ride.origin_label or "Origin",
        })
    for stop in ride.stops.all():
        if stop.lat is not None and stop.lng is not None:
            markers.append({
                "lat": float(stop.lat),
                "lng": float(stop.lng),
                "label": stop.label or "Stop",
            })
    return markers


def _employee_or_none(user):
    try:
        return user.employee_profile
    except Exception:
        return None


def _driver_or_none(user):
    emp = _employee_or_none(user)
    if not emp:
        return None
    try:
        return emp.driver_profile
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Hub / fleet
# ---------------------------------------------------------------------------

@login_required
def hub(request):
    """Landing: fleet managers see ops; employees see my rides + available carpools."""
    can_manage = user_has_permission(request.user, "manage_transport")
    can_view = can_manage or user_has_permission(request.user, "view_transport")
    can_history = _can_view_transport_history(request.user)
    can_live = (
        can_manage
        or user_has_permission(request.user, "view_live_tracking")
    )
    emp = _employee_or_none(request.user)
    driver = _driver_or_none(request.user)

    my_rides = Ride.objects.none()
    if emp or request.user.is_authenticated:
        my_rides = (
            services.rides_queryset_for_user(request.user)
            .select_related("vehicle", "driver__employee__user")
            .order_by("-scheduled_departure")[:10]
        )

    open_carpools = Ride.objects.filter(
        allow_carpool=True,
        status__in=services.JOINABLE_CARPOOL_STATUSES,
    ).select_related("vehicle", "driver__employee__user").annotate(
        pax=Count("passengers")
    ).order_by("scheduled_departure")[:12]
    # Hide carpools the user is already on
    if emp:
        open_carpools = open_carpools.exclude(
            Q(requester=emp) | Q(passengers__employee=emp)
        ).distinct()

    stats = {}
    due_reminders = []
    if can_view or can_manage:
        stats = {
            "vehicles": Vehicle.objects.filter(is_active=True).count(),
            "drivers": Driver.objects.filter(status="active").count(),
            "active_rides": Ride.objects.filter(
                status__in=services.ACTIVE_RIDE_STATUSES
            ).count(),
            "pending_approvals": Ride.objects.filter(status=RideStatus.PENDING_APPROVAL).count(),
            "in_progress": Ride.objects.filter(status=RideStatus.IN_PROGRESS).count(),
        }
        due_reminders = services.fleet_due_items()[:12]

    return render(request, "transport/hub.html", {
        "can_manage": can_manage,
        "can_view": can_view or can_manage,
        "can_history": can_history,
        "can_live": can_live,
        "can_create": user_has_permission(request.user, "create_ride") or can_manage,
        "can_approve": (
            user_has_permission(request.user, "approve_transport")
            or can_manage
            or bool(services.pending_approvals_for_user(request.user))
        ),
        "is_driver": bool(driver),
        "my_rides": my_rides,
        "open_carpools": open_carpools,
        "stats": stats,
        "due_reminders": due_reminders,
        "employee": emp,
    })


@login_required
@permission_required("manage_transport")
def policy_edit(request):
    policy = TransportationPolicy.current()
    if request.method == "POST":
        form = TransportationPolicyForm(request.POST, instance=policy)
        if form.is_valid():
            form.save()
            messages.success(request, "Transportation policy updated.")
            return redirect("transport:policy")
        messages.error(request, "Could not save policy. Check the form.")
    else:
        form = TransportationPolicyForm(instance=policy)
    return render(request, "transport/policy.html", {
        "form": form,
        "policy": policy,
    })


@login_required
@permission_required("view_transport")
def schedule(request):
    vehicle_id = request.GET.get("vehicle") or ""
    vehicles = Vehicle.objects.filter(is_active=True).order_by("name")
    vid = None
    if vehicle_id.isdigit():
        vid = int(vehicle_id)
    import json
    events = services.schedule_calendar_events(vehicle_id=vid)
    return render(request, "transport/schedule.html", {
        "vehicles": vehicles,
        "selected_vehicle": vid,
        "events_json": json.dumps(events),
        "can_manage": user_has_permission(request.user, "manage_transport"),
    })


@login_required
@permission_required("view_transport")
def vehicle_list(request):
    vehicles = list(Vehicle.objects.select_related("branch").all())
    due_by_vehicle = {}
    for item in services.fleet_due_items():
        due_by_vehicle.setdefault(item["vehicle_id"], []).append(item)
    for v in vehicles:
        v.due_chips = []
        for item in due_by_vehicle.get(v.pk, []):
            prefix = "Overdue" if item["status"] == "overdue" else "Due soon"
            short = item["label"]
            if len(short) > 36:
                short = short[:33] + "…"
            v.due_chips.append({"text": f"{prefix}: {short}", "status": item["status"]})
    return render(request, "transport/vehicles.html", {
        "vehicles": vehicles,
        "can_manage": user_has_permission(request.user, "manage_transport"),
        "form": VehicleForm() if user_has_permission(request.user, "manage_transport") else None,
        "due_reminders": services.fleet_due_items()[:15],
    })


@login_required
@permission_required("manage_transport")
def vehicle_create(request):
    if request.method == "POST":
        form = VehicleForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehicle registered.")
        else:
            messages.error(request, "Could not save vehicle.")
    return redirect("transport:vehicles")


@login_required
@permission_required("manage_transport")
def vehicle_edit(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if request.method == "POST":
        form = VehicleForm(request.POST, request.FILES, instance=vehicle)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehicle updated.")
        else:
            messages.error(request, "Could not update vehicle.")
    return redirect("transport:vehicles")


@login_required
@permission_required("view_transport")
def vehicle_detail(request, pk):
    vehicle = get_object_or_404(
        Vehicle.objects.prefetch_related(
            "documents",
            "fuel_entries__driver__employee__user",
            "maintenance_records",
            "rides",
        ),
        pk=pk,
    )
    can_manage = user_has_permission(request.user, "manage_transport")
    return render(request, "transport/vehicle_detail.html", {
        "vehicle": vehicle,
        "can_manage": can_manage,
        "doc_form": VehicleDocumentForm() if can_manage else None,
        "fuel_form": FuelEntryForm(vehicle=vehicle) if can_manage else None,
        "maint_form": MaintenanceRecordForm(vehicle=vehicle) if can_manage else None,
        "fuel_entries": vehicle.fuel_entries.all()[:20],
        "maintenance_records": vehicle.maintenance_records.all()[:20],
        "due_chips": services.vehicle_due_chips(vehicle),
        "upcoming": vehicle.rides.filter(
            status__in=services.ACTIVE_RIDE_STATUSES + [RideStatus.PENDING_APPROVAL]
        ).order_by("scheduled_departure")[:10],
    })


@login_required
@permission_required("manage_transport")
@require_POST
def vehicle_document_add(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    form = VehicleDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.vehicle = vehicle
        doc.save()
        messages.success(request, "Document uploaded.")
    else:
        messages.error(request, "Could not upload document.")
    return redirect("transport:vehicle_detail", pk=pk)


# ---------------------------------------------------------------------------
# Phase 5 — Fuel & maintenance
# ---------------------------------------------------------------------------

@login_required
@permission_required("view_transport")
def fuel_list(request):
    entries = (
        FuelEntry.objects.select_related("vehicle", "driver__employee__user", "recorded_by")
        .all()[:200]
    )
    can_manage = user_has_permission(request.user, "manage_transport")
    return render(request, "transport/fuel_list.html", {
        "entries": entries,
        "can_manage": can_manage,
        "form": FuelEntryForm() if can_manage else None,
        "due_reminders": services.fleet_due_items()[:10],
    })


@login_required
@permission_required("manage_transport")
def fuel_create(request):
    vehicle_id = request.POST.get("vehicle") or request.GET.get("vehicle")
    vehicle = None
    if vehicle_id:
        vehicle = Vehicle.objects.filter(pk=vehicle_id).first()
    if request.method == "POST":
        form = FuelEntryForm(request.POST, request.FILES, vehicle=vehicle)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.recorded_by = request.user
            if entry.total is None and entry.litres is not None and entry.price_per_litre is not None:
                entry.total = entry.litres * entry.price_per_litre
            entry.save()
            messages.success(request, "Fuel entry saved.")
            if request.POST.get("next") == "vehicle" and entry.vehicle_id:
                return redirect("transport:vehicle_detail", pk=entry.vehicle_id)
            return redirect("transport:fuel_list")
        messages.error(request, "Could not save fuel entry.")
        if vehicle:
            return redirect("transport:vehicle_detail", pk=vehicle.pk)
        return redirect("transport:fuel_list")
    return redirect("transport:fuel_list")


@login_required
@permission_required("manage_transport")
@require_POST
def fuel_delete(request, pk):
    entry = get_object_or_404(FuelEntry, pk=pk)
    vehicle_id = entry.vehicle_id
    entry.delete()
    messages.success(request, "Fuel entry deleted.")
    if request.POST.get("next") == "vehicle":
        return redirect("transport:vehicle_detail", pk=vehicle_id)
    return redirect("transport:fuel_list")


@login_required
@permission_required("view_transport")
def maintenance_list(request):
    records = (
        MaintenanceRecord.objects.select_related("vehicle", "recorded_by")
        .all()[:200]
    )
    can_manage = user_has_permission(request.user, "manage_transport")
    return render(request, "transport/maintenance_list.html", {
        "records": records,
        "can_manage": can_manage,
        "form": MaintenanceRecordForm() if can_manage else None,
        "due_reminders": services.fleet_due_items()[:10],
    })


@login_required
@permission_required("manage_transport")
def maintenance_create(request):
    vehicle_id = request.POST.get("vehicle") or request.GET.get("vehicle")
    vehicle = None
    if vehicle_id:
        vehicle = Vehicle.objects.filter(pk=vehicle_id).first()
    if request.method == "POST":
        form = MaintenanceRecordForm(request.POST, request.FILES, vehicle=vehicle)
        if form.is_valid():
            rec = form.save(commit=False)
            rec.recorded_by = request.user
            rec.save()
            messages.success(request, "Maintenance record saved.")
            if request.POST.get("next") == "vehicle" and rec.vehicle_id:
                return redirect("transport:vehicle_detail", pk=rec.vehicle_id)
            return redirect("transport:maintenance_list")
        messages.error(request, "Could not save maintenance record.")
        if vehicle:
            return redirect("transport:vehicle_detail", pk=vehicle.pk)
        return redirect("transport:maintenance_list")
    return redirect("transport:maintenance_list")


@login_required
@permission_required("manage_transport")
@require_POST
def maintenance_delete(request, pk):
    rec = get_object_or_404(MaintenanceRecord, pk=pk)
    vehicle_id = rec.vehicle_id
    rec.delete()
    messages.success(request, "Maintenance record deleted.")
    if request.POST.get("next") == "vehicle":
        return redirect("transport:vehicle_detail", pk=vehicle_id)
    return redirect("transport:maintenance_list")


# ---------------------------------------------------------------------------
# Phase 6 — Analytics
# ---------------------------------------------------------------------------

@login_required
def transport_analytics(request):
    can_manage = user_has_permission(request.user, "manage_transport")
    can_view = can_manage or user_has_permission(request.user, "view_transport")
    if not can_view:
        messages.error(request, "You don't have permission to view transport analytics.")
        return redirect("transport:hub")

    range_key = (request.GET.get("range") or "this_month").strip().lower()
    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")
    start, end, range_key = services.resolve_analytics_range(range_key, date_from, date_to)
    stats = services.transport_analytics(start, end)

    import json
    return render(request, "transport/analytics.html", {
        "can_manage": can_manage,
        "stats": stats,
        "range_key": range_key,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "month_labels_json": json.dumps(stats["month_labels"]),
        "month_counts_json": json.dumps(stats["month_counts"]),
        "status_labels_json": json.dumps(stats["status_labels"]),
        "status_counts_json": json.dumps(stats["status_counts"]),
    })


@login_required
@permission_required("view_transport")
def driver_list(request):
    drivers = Driver.objects.select_related("employee__user", "default_vehicle").all()
    return render(request, "transport/drivers.html", {
        "drivers": drivers,
        "can_manage": user_has_permission(request.user, "manage_transport"),
        "form": DriverForm() if user_has_permission(request.user, "manage_transport") else None,
    })


@login_required
@permission_required("manage_transport")
def driver_create(request):
    if request.method == "POST":
        form = DriverForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Driver profile created.")
        else:
            messages.error(request, "Could not create driver. Employee may already have a profile.")
    return redirect("transport:drivers")


@login_required
@permission_required("manage_transport")
def driver_edit(request, pk):
    driver = get_object_or_404(Driver, pk=pk)
    if request.method == "POST":
        form = DriverForm(request.POST, instance=driver)
        if form.is_valid():
            form.save()
            messages.success(request, "Driver updated.")
        else:
            messages.error(request, "Could not update driver.")
    return redirect("transport:drivers")


# ---------------------------------------------------------------------------
# Rides
# ---------------------------------------------------------------------------

@login_required
def ride_list(request):
    can_manage = user_has_permission(request.user, "manage_transport")
    qs = Ride.objects.select_related(
        "vehicle", "driver__employee__user", "requester__user", "organizer",
    )
    rides = services.rides_queryset_for_user(request.user, qs).order_by(
        "-scheduled_departure", "-created_at",
    )[:100 if services.user_has_transport_ops_access(request.user) else 50]
    return render(request, "transport/rides.html", {
        "rides": rides,
        "can_create": user_has_permission(request.user, "create_ride") or can_manage,
        "can_manage": can_manage,
    })


def _can_view_transport_history(user) -> bool:
    """History page: ops roles or anyone with create_ride (scoped to own rides)."""
    return (
        services.user_has_transport_ops_access(user)
        or user_has_permission(user, "create_ride")
        or getattr(user, "is_superuser", False)
    )


@login_required
def transport_history(request):
    """
    Transport history: ops see org-wide; employees see only rides they participate in.
    """
    if not _can_view_transport_history(request.user):
        messages.error(request, "You don't have permission to view transport history.")
        return redirect("transport:hub")

    is_ops = services.user_has_transport_ops_access(request.user)
    tab = (request.GET.get("tab") or "requests").strip().lower()
    if tab not in {"requests", "approvals", "activity"}:
        tab = "requests"
    if not is_ops and tab in {"approvals", "activity"}:
        tab = "requests"

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    ride_type = (request.GET.get("ride_type") or "").strip()
    event_type = (request.GET.get("event_type") or "").strip()
    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")

    rides_qs = services.rides_queryset_for_user(
        request.user,
        Ride.objects.select_related(
            "vehicle", "driver__employee__user", "requester__user", "organizer",
        ).prefetch_related("passengers", "approval_steps"),
    )

    if q:
        rides_qs = rides_qs.filter(
            Q(reference__icontains=q)
            | Q(origin_label__icontains=q)
            | Q(purpose__icontains=q)
            | Q(vehicle__registration_number__icontains=q)
            | Q(vehicle__name__icontains=q)
            | Q(requester__user__first_name__icontains=q)
            | Q(requester__user__last_name__icontains=q)
            | Q(organizer__first_name__icontains=q)
            | Q(organizer__last_name__icontains=q)
        )
    if status and status in RideStatus.values:
        rides_qs = rides_qs.filter(status=status)
    if ride_type and ride_type in RideType.values:
        rides_qs = rides_qs.filter(ride_type=ride_type)
    if date_from:
        rides_qs = rides_qs.filter(scheduled_departure__date__gte=date_from)
    if date_to:
        rides_qs = rides_qs.filter(scheduled_departure__date__lte=date_to)

    visible_ride_ids = None
    if not is_ops:
        visible_ride_ids = list(rides_qs.values_list("id", flat=True)[:5000])

    events_qs = RideEvent.objects.select_related(
        "ride", "ride__vehicle", "actor", "passenger__employee__user",
    ).order_by("-created_at")
    if visible_ride_ids is not None:
        events_qs = events_qs.filter(ride_id__in=visible_ride_ids)
    if q:
        events_qs = events_qs.filter(
            Q(ride__reference__icontains=q)
            | Q(message__icontains=q)
            | Q(actor__first_name__icontains=q)
            | Q(actor__last_name__icontains=q)
            | Q(actor__username__icontains=q)
        )
    if status and status in RideStatus.values:
        events_qs = events_qs.filter(ride__status=status)
    if ride_type and ride_type in RideType.values:
        events_qs = events_qs.filter(ride__ride_type=ride_type)
    if event_type and event_type in RideEventType.values:
        events_qs = events_qs.filter(event_type=event_type)
    if date_from:
        events_qs = events_qs.filter(created_at__date__gte=date_from)
    if date_to:
        events_qs = events_qs.filter(created_at__date__lte=date_to)

    approvals_qs = RideApprovalStep.objects.filter(
        status__in=[StepStatus.APPROVED, StepStatus.REJECTED, StepStatus.PENDING, StepStatus.SKIPPED],
    ).select_related(
        "ride", "ride__vehicle", "ride__requester__user", "acted_by",
    ).order_by("-acted_at", "-id")
    if visible_ride_ids is not None:
        approvals_qs = approvals_qs.filter(ride_id__in=visible_ride_ids)
    if q:
        approvals_qs = approvals_qs.filter(
            Q(ride__reference__icontains=q)
            | Q(note__icontains=q)
            | Q(acted_by__first_name__icontains=q)
            | Q(acted_by__last_name__icontains=q)
            | Q(acted_by__username__icontains=q)
        )
    if status and status in RideStatus.values:
        approvals_qs = approvals_qs.filter(ride__status=status)
    if ride_type and ride_type in RideType.values:
        approvals_qs = approvals_qs.filter(ride__ride_type=ride_type)
    if date_from:
        approvals_qs = approvals_qs.filter(
            Q(acted_at__date__gte=date_from) | Q(acted_at__isnull=True, ride__created_at__date__gte=date_from)
        )
    if date_to:
        approvals_qs = approvals_qs.filter(
            Q(acted_at__date__lte=date_to) | Q(acted_at__isnull=True, ride__created_at__date__lte=date_to)
        )

    if tab == "approvals":
        page_obj = Paginator(approvals_qs, 25).get_page(request.GET.get("page"))
    elif tab == "activity":
        page_obj = Paginator(events_qs, 40).get_page(request.GET.get("page"))
    else:
        page_obj = Paginator(rides_qs.order_by("-scheduled_departure", "-created_at"), 25).get_page(
            request.GET.get("page")
        )

    scoped_rides = services.rides_queryset_for_user(request.user)
    status_counts = {
        row["status"]: row["c"]
        for row in scoped_rides.values("status").annotate(c=Count("id"))
    }
    stats = {
        "total_rides": scoped_rides.count(),
        "pending": status_counts.get(RideStatus.PENDING_APPROVAL, 0),
        "active": scoped_rides.filter(status__in=services.ACTIVE_RIDE_STATUSES).count(),
        "completed": status_counts.get(RideStatus.COMPLETED, 0),
        "rejected": status_counts.get(RideStatus.REJECTED, 0),
        "cancelled": (
            status_counts.get(RideStatus.CANCELLED, 0)
            + status_counts.get(RideStatus.ABORTED, 0)
        ),
        "events": events_qs.count() if not is_ops else RideEvent.objects.count(),
        "approval_decisions": (
            RideApprovalStep.objects.filter(
                status__in=[StepStatus.APPROVED, StepStatus.REJECTED],
                ride_id__in=visible_ride_ids,
            ).count()
            if visible_ride_ids is not None
            else RideApprovalStep.objects.filter(
                status__in=[StepStatus.APPROVED, StepStatus.REJECTED]
            ).count()
        ),
    }

    filter_params = request.GET.copy()
    filter_params.pop("page", None)
    filter_query = filter_params.urlencode()

    return render(request, "transport/history.html", {
        "tab": tab,
        "page_obj": page_obj,
        "stats": stats,
        "status_choices": RideStatus.choices,
        "ride_type_choices": RideType.choices,
        "event_type_choices": RideEventType.choices,
        "selected_status": status,
        "selected_ride_type": ride_type,
        "selected_event_type": event_type,
        "date_from": request.GET.get("date_from") or "",
        "date_to": request.GET.get("date_to") or "",
        "q": q,
        "filter_query": filter_query,
        "can_manage": user_has_permission(request.user, "manage_transport"),
        "is_ops": is_ops,
    })


def _vehicle_form_maps():
    """JS maps: vehicle id → photo URL / default driver id."""
    import json
    photo_map = {}
    driver_map = {}
    for v in Vehicle.objects.filter(is_active=True).prefetch_related("default_drivers"):
        if v.photo:
            photo_map[str(v.pk)] = v.photo.url
        d = v.default_drivers.filter(status="active").first()
        if d:
            driver_map[str(v.pk)] = d.pk
    return {
        "vehicle_photo_map_json": json.dumps(photo_map),
        "vehicle_default_driver_map_json": json.dumps(driver_map),
    }


@login_required
def ride_create(request):
    if not (
        user_has_permission(request.user, "create_ride")
        or user_has_permission(request.user, "manage_transport")
    ):
        messages.error(request, "You don't have permission to request a ride.")
        return redirect("transport:hub")
    emp = _employee_or_none(request.user)
    if not emp and not user_has_permission(request.user, "manage_transport"):
        messages.error(request, "You need an employee profile to request a ride.")
        return redirect("transport:hub")

    if request.method == "POST":
        form = RideRequestForm(request.POST)
        if form.is_valid():
            try:
                ride = services.create_ride_request(
                    organizer=request.user,
                    requester_employee=emp,
                    vehicle=form.cleaned_data["vehicle"],
                    origin_label=form.cleaned_data["origin_label"],
                    destination_label=form.cleaned_data["destination_label"],
                    scheduled_departure=form.cleaned_data["scheduled_departure"],
                    purpose=form.cleaned_data.get("purpose") or "",
                    driver=form.cleaned_data.get("driver"),
                    scheduled_return=form.cleaned_data.get("scheduled_return"),
                    estimated_distance_km=form.cleaned_data.get("estimated_distance_km"),
                    estimated_duration_min=form.cleaned_data.get("estimated_duration_min"),
                    origin_lat=form.cleaned_data.get("origin_lat"),
                    origin_lng=form.cleaned_data.get("origin_lng"),
                    destination_lat=form.cleaned_data.get("destination_lat"),
                    destination_lng=form.cleaned_data.get("destination_lng"),
                    route_geometry=form.cleaned_route_geometry(),
                    route_provider=form.cleaned_data.get("route_provider") or "",
                    allow_carpool=form.cleaned_data.get("allow_carpool", True),
                    ride_type=form.cleaned_data.get("ride_type") or "official",
                )
                if request.POST.get("submit_now") == "1":
                    if not emp:
                        messages.error(request, "An employee requester is required to submit for approval.")
                    else:
                        services.submit_ride(ride, request.user)
                        messages.success(request, f"Ride {ride.reference} submitted for approval.")
                else:
                    messages.success(request, f"Draft ride {ride.reference} saved.")
                return redirect("transport:ride_detail", pk=ride.pk)
            except ValueError as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, "Please fix the form errors.")
    else:
        form = RideRequestForm()

    return render(request, "transport/ride_form.html", {
        "form": form,
        **_map_defaults(),
        **_vehicle_form_maps(),
    })


@login_required
@permission_required("manage_transport")
def shuttle_create(request):
    """Organizer creates a multi-passenger shuttle (no single passenger owns the ride)."""
    PassengerFormSet = make_shuttle_passenger_formset(extra=3)
    if request.method == "POST":
        form = ShuttleRideForm(request.POST)
        formset = PassengerFormSet(request.POST, prefix="pax")
        if form.is_valid() and formset.is_valid():
            passengers = []
            for row in formset:
                if not hasattr(row, "cleaned_data") or not row.cleaned_data:
                    continue
                if row.cleaned_data.get("DELETE"):
                    continue
                emp = row.cleaned_data.get("employee")
                dest = (row.cleaned_data.get("destination_label") or "").strip()
                if emp and dest:
                    passengers.append({
                        "employee": emp,
                        "destination_label": dest,
                        "destination_lat": row.cleaned_data.get("destination_lat"),
                        "destination_lng": row.cleaned_data.get("destination_lng"),
                    })
            try:
                ride = services.create_shuttle_ride(
                    organizer=request.user,
                    vehicle=form.cleaned_data["vehicle"],
                    origin_label=form.cleaned_data["origin_label"],
                    scheduled_departure=form.cleaned_data["scheduled_departure"],
                    passengers=passengers,
                    purpose=form.cleaned_data.get("purpose") or "Company shuttle",
                    driver=form.cleaned_data.get("driver"),
                    scheduled_return=form.cleaned_data.get("scheduled_return"),
                    origin_lat=form.cleaned_data.get("origin_lat"),
                    origin_lng=form.cleaned_data.get("origin_lng"),
                    allow_carpool=form.cleaned_data.get("allow_carpool", False),
                    estimated_distance_km=form.cleaned_data.get("estimated_distance_km"),
                    estimated_duration_min=form.cleaned_data.get("estimated_duration_min"),
                    route_geometry=form.cleaned_route_geometry(),
                    route_provider=form.cleaned_data.get("route_provider") or "",
                    submit=request.POST.get("submit_now") == "1",
                )
                if request.POST.get("submit_now") == "1":
                    messages.success(request, f"Shuttle {ride.reference} submitted for transport approval.")
                else:
                    messages.success(request, f"Shuttle draft {ride.reference} saved.")
                return redirect("transport:ride_detail", pk=ride.pk)
            except ValueError as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, "Please fix the shuttle form errors.")
    else:
        form = ShuttleRideForm()
        formset = PassengerFormSet(prefix="pax")

    return render(request, "transport/shuttle_form.html", {
        "form": form,
        "formset": formset,
        **_map_defaults(),
        **_vehicle_form_maps(),
    })


@login_required
@require_GET
def api_geocode(request):
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    return JsonResponse({"results": geocode(q, limit=6)})


@login_required
@require_POST
def api_route(request):
    """JSON body: {points: [{lat,lng,label?}, ...]} → distance, duration, geometry."""
    import json
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    raw_points = payload.get("points") or []
    points = []
    for p in raw_points:
        try:
            points.append(GeoPoint(float(p["lat"]), float(p["lng"]), p.get("label") or ""))
        except (KeyError, TypeError, ValueError):
            continue
    if len(points) < 2:
        return JsonResponse({"error": "Need at least origin and one stop"}, status=400)
    result = estimate_route_or_fallback(points)
    return JsonResponse({
        "distance_km": str(result.distance_km),
        "duration_min": result.duration_min,
        "geometry": result.geometry,
        "provider": result.provider,
        "waypoints": result.waypoints,
    })


@login_required
def ride_detail(request, pk):
    ride = get_object_or_404(
        Ride.objects.select_related(
            "vehicle", "driver__employee__user", "requester__user", "organizer",
        ).prefetch_related(
            "passengers__employee__user",
            "stops__passengers",
            "events__actor",
            "approval_steps__acted_by",
            "join_requests__employee__user",
        ),
        pk=pk,
    )
    emp = _employee_or_none(request.user)
    driver = _driver_or_none(request.user)
    can_manage = user_has_permission(request.user, "manage_transport")
    is_organizer = ride.organizer_id == request.user.id
    is_passenger = emp and ride.passengers.filter(employee=emp).exists()
    is_requester = emp and ride.requester_id == emp.id
    is_assigned_driver = driver and ride.driver_id == driver.id
    is_participant = services.user_is_ride_participant(request.user, ride)
    is_ops = services.user_has_transport_ops_access(request.user)

    if not services.user_can_view_ride(request.user, ride):
        messages.error(request, "You cannot view this ride.")
        return redirect("transport:hub")

    # Carpool preview: joinable but not a participant and not ops — limited UI
    carpool_preview = (
        not is_participant
        and not is_ops
        and services.ride_is_joinable_carpool(ride)
        and emp
        and not is_passenger
    )

    can_operate = services.user_can_operate_journey(request.user, ride)

    return render(request, "transport/ride_detail.html", {
        "ride": ride,
        "events": (
            [] if carpool_preview
            else ride.events.select_related("actor", "passenger__employee__user")[:80]
        ),
        "can_manage": can_manage,
        "carpool_preview": carpool_preview,
        "can_review": (not carpool_preview) and services.user_can_review_ride(request.user, ride),
        "can_submit": (not carpool_preview) and ride.status == RideStatus.DRAFT and (
            is_organizer or is_requester or can_manage
        ),
        "can_accept_driver": ride.status == RideStatus.DRIVER_PENDING and (
            is_assigned_driver or can_manage
        ),
        "can_start": ride.status in (RideStatus.READY, RideStatus.DRIVER_ACCEPTED) and can_operate,
        "can_complete": ride.status == RideStatus.IN_PROGRESS and can_operate,
        "can_board": ride.status in (
            RideStatus.READY, RideStatus.DRIVER_ACCEPTED, RideStatus.IN_PROGRESS,
        ) and can_operate,
        "can_cancel": (
            (not carpool_preview)
            and services.user_can_cancel_ride(request.user, ride)
            and ride.status not in (
                RideStatus.COMPLETED, RideStatus.CANCELLED, RideStatus.ABORTED, RideStatus.IN_PROGRESS,
            )
        ),
        "can_leave": (
            is_passenger
            and ride.status != RideStatus.IN_PROGRESS
            and ride.status not in (
                RideStatus.COMPLETED, RideStatus.CANCELLED, RideStatus.ABORTED,
            )
            and not is_requester  # requester cancels whole ride instead
        ),
        "can_join": (
            emp and ride.allow_carpool
            and not is_passenger
            and ride.status in services.JOINABLE_CARPOOL_STATUSES
        ),
        "is_organizer": is_organizer,
        "is_passenger": is_passenger,
        "show_journey_link": ride.status == RideStatus.IN_PROGRESS and (
            is_passenger or is_requester or is_assigned_driver or can_manage
        ),
        "cancel_reason_required": (
            TransportationPolicy.current().require_cancel_reason_after_approval
            and ride.status not in (RideStatus.DRAFT, RideStatus.SUBMITTED)
        ),
        "join_form": JoinRequestForm(),
        "review_form": ReviewForm(),
        "cancel_form": CancelRideForm(),
        "pending_joins": (
            [] if carpool_preview
            else ride.join_requests.filter(
                status__in=[
                    JoinRequestStatus.PENDING,
                    JoinRequestStatus.ORGANIZER_APPROVED,
                    JoinRequestStatus.ADMIN_APPROVED,
                ]
            )
        ),
        "employee": emp,
        "route_geometry_json": ride.route_geometry or {},
        "map_markers": _ride_map_markers(ride),
        **_map_defaults(),
    })


@login_required
@require_POST
def ride_submit(request, pk):
    ride = get_object_or_404(Ride, pk=pk)
    try:
        services.submit_ride(ride, request.user)
        messages.success(request, f"{ride.reference} submitted for approval.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("transport:ride_detail", pk=pk)


@login_required
@require_POST
def ride_cancel(request, pk):
    ride = get_object_or_404(Ride, pk=pk)
    reason = request.POST.get("reason", "")
    try:
        services.cancel_ride(ride, request.user, reason=reason)
        messages.success(request, "Ride cancelled.")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect("transport:ride_detail", pk=pk)


@login_required
@require_POST
def passenger_leave(request, pk):
    ride = get_object_or_404(Ride, pk=pk)
    emp = _employee_or_none(request.user)
    if not emp:
        messages.error(request, "Employee profile required.")
        return redirect("transport:ride_detail", pk=pk)
    try:
        services.passenger_leave_ride(ride, emp, request.user, reason=request.POST.get("reason", ""))
        messages.success(request, "You left this ride.")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect("transport:hub")


@login_required
def approvals(request):
    """Transport ride approvals only — not leave approvals."""
    if not (
        user_has_permission(request.user, "approve_transport")
        or user_has_permission(request.user, "manage_transport")
        or getattr(request.user, "is_superuser", False)
        or services.pending_approvals_for_user(request.user)
    ):
        # Department managers without approve_transport may still act via manager stage
        pass
    pending = services.pending_approvals_for_user(request.user)
    return render(request, "transport/approvals.html", {
        "pending": pending,
        "review_form": ReviewForm(),
    })


@login_required
@require_POST
def ride_review(request, pk, action):
    ride = get_object_or_404(Ride, pk=pk)
    action = (action or "").strip().lower()
    if action not in ("approve", "reject"):
        messages.error(request, "Invalid review action.")
        return redirect("transport:approvals")
    note = request.POST.get("note", "")
    try:
        services.process_approval(ride, request.user, action, note)
        label = "approved" if action == "approve" else "rejected"
        messages.success(request, f"Ride {label}.")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    next_url = request.POST.get("next") or ""
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("transport:approvals")


# ---------------------------------------------------------------------------
# Driver portal
# ---------------------------------------------------------------------------

@login_required
def driver_portal(request):
    driver = _driver_or_none(request.user)
    if not driver and not user_has_permission(request.user, "manage_transport"):
        messages.error(request, "You are not registered as a driver.")
        return redirect("transport:hub")
    qs = Ride.objects.select_related("vehicle", "requester__user").prefetch_related(
        "passengers__employee__user", "stops",
    )
    if driver:
        assigned = qs.filter(driver=driver).exclude(
            status__in=[RideStatus.COMPLETED, RideStatus.CANCELLED, RideStatus.REJECTED, RideStatus.ABORTED, RideStatus.DRAFT]
        ).order_by("scheduled_departure")
    else:
        assigned = qs.filter(status__in=services.ACTIVE_RIDE_STATUSES).order_by("scheduled_departure")[:20]

    policy = TransportationPolicy.current()
    trackable = [
        {
            "id": r.id,
            "reference": r.reference,
            "status": r.status,
            "origin_lat": float(r.origin_lat) if r.origin_lat is not None else None,
            "origin_lng": float(r.origin_lng) if r.origin_lng is not None else None,
            "ping_url": f"/transport/api/rides/{r.id}/location/",
            "passengers": [
                {
                    "id": p.id,
                    "name": p.employee.full_name,
                    "destination": p.destination_label,
                    "status": p.status,
                    "lat": float(p.destination_lat) if p.destination_lat is not None else (
                        float(p.stop.lat) if p.stop_id and p.stop and p.stop.lat is not None else None
                    ),
                    "lng": float(p.destination_lng) if p.destination_lng is not None else (
                        float(p.stop.lng) if p.stop_id and p.stop and p.stop.lng is not None else None
                    ),
                }
                for p in r.passengers.all()
            ],
        }
        for r in assigned
        if r.status in (RideStatus.READY, RideStatus.DRIVER_ACCEPTED, RideStatus.IN_PROGRESS)
    ]

    return render(request, "transport/driver_portal.html", {
        "driver": driver,
        "assigned": assigned,
        "trackable_json": trackable,
        "geofence_radius": policy.geofence_radius_metres,
        "auto_start_enabled": policy.auto_start_enabled,
        "auto_arrival_enabled": policy.auto_arrival_enabled,
        **_map_defaults(),
    })


@login_required
@require_POST
def driver_accept_ride(request, pk):
    ride = get_object_or_404(Ride, pk=pk)
    try:
        services.driver_accept(ride, request.user)
        messages.success(request, "Assignment accepted.")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect("transport:driver_portal")


@login_required
@require_POST
def driver_decline_ride(request, pk):
    ride = get_object_or_404(Ride, pk=pk)
    try:
        services.driver_decline(ride, request.user, note=request.POST.get("note", ""))
        messages.success(request, "Assignment declined.")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect("transport:driver_portal")


@login_required
@require_POST
def ride_start(request, pk):
    ride = get_object_or_404(Ride, pk=pk)
    try:
        services.start_journey(ride, request.user)
        messages.success(request, "Journey started.")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    next_url = request.POST.get("next") or ""
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("transport:ride_detail", pk=pk)


@login_required
@require_POST
def ride_complete(request, pk):
    ride = get_object_or_404(Ride, pk=pk)
    try:
        services.complete_ride(ride, request.user)
        messages.success(request, "Ride completed.")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect("transport:ride_detail", pk=pk)


@login_required
@require_POST
def passenger_arrived(request, pk, passenger_id):
    ride = get_object_or_404(Ride, pk=pk)
    passenger = get_object_or_404(RidePassenger, pk=passenger_id, ride=ride)
    try:
        services.mark_passenger_arrived(ride, passenger, request.user)
        messages.success(request, f"Marked arrived: {passenger.destination_label}")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    next_url = request.POST.get("next") or ""
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("transport:ride_detail", pk=pk)


@login_required
@require_POST
def passenger_boarding(request, pk, passenger_id):
    ride = get_object_or_404(Ride, pk=pk)
    passenger = get_object_or_404(RidePassenger, pk=passenger_id, ride=ride)
    try:
        services.mark_passenger_boarding(ride, passenger, request.user)
        messages.success(request, f"Boarding: {passenger.employee}")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    next_url = request.POST.get("next") or ""
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("transport:ride_detail", pk=pk)


@login_required
@require_POST
def passenger_onboard(request, pk, passenger_id):
    ride = get_object_or_404(Ride, pk=pk)
    passenger = get_object_or_404(RidePassenger, pk=passenger_id, ride=ride)
    try:
        services.mark_passenger_onboard(ride, passenger, request.user)
        messages.success(request, f"On board: {passenger.employee}")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    next_url = request.POST.get("next") or ""
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("transport:ride_detail", pk=pk)


@login_required
def ride_journey(request, pk):
    """Passenger-facing live journey status + map."""
    ride = get_object_or_404(
        Ride.objects.select_related("vehicle", "driver__employee__user").prefetch_related("stops"),
        pk=pk,
    )
    emp = _employee_or_none(request.user)
    driver = _driver_or_none(request.user)
    can_manage = user_has_permission(request.user, "manage_transport")
    is_passenger = emp and ride.passengers.filter(employee=emp).exists()
    is_requester = emp and ride.requester_id == emp.id
    is_assigned_driver = driver and ride.driver_id == driver.id
    if not (can_manage or is_passenger or is_requester or is_assigned_driver
            or user_has_permission(request.user, "view_live_tracking")):
        messages.error(request, "You cannot view this journey.")
        return redirect("transport:hub")

    my_passenger = None
    if emp:
        my_passenger = ride.passengers.filter(employee=emp).first()

    import json
    payload = services.passenger_journey_payload(ride)
    return render(request, "transport/journey.html", {
        "ride": ride,
        "my_passenger": my_passenger,
        "payload": payload,
        "payload_json": json.dumps(payload),
        **_map_defaults(),
    })


@login_required
@require_GET
def api_ride_journey(request, pk):
    """JSON poll for passenger journey page (scoped to ride participants)."""
    ride = get_object_or_404(Ride.objects.prefetch_related("stops"), pk=pk)
    emp = _employee_or_none(request.user)
    driver = _driver_or_none(request.user)
    can_manage = user_has_permission(request.user, "manage_transport")
    allowed = (
        can_manage
        or user_has_permission(request.user, "view_live_tracking")
        or (emp and ride.passengers.filter(employee=emp).exists())
        or (emp and ride.requester_id == emp.id)
        or (driver and ride.driver_id == driver.id)
    )
    if not allowed:
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(services.passenger_journey_payload(ride))


# ---------------------------------------------------------------------------
# Carpool
# ---------------------------------------------------------------------------

@login_required
@require_POST
def join_request_create(request, pk):
    ride = get_object_or_404(Ride, pk=pk)
    emp = _employee_or_none(request.user)
    if not emp:
        messages.error(request, "You need an employee profile to join a ride.")
        return redirect("transport:ride_detail", pk=pk)
    form = JoinRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter your destination.")
        return redirect("transport:ride_detail", pk=pk)
    try:
        services.request_to_join(
            ride,
            emp,
            form.cleaned_data["destination_label"],
            destination_lat=form.cleaned_data.get("destination_lat"),
            destination_lng=form.cleaned_data.get("destination_lng"),
        )
        messages.success(request, "Join request submitted. Awaiting organizer and transport approval.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("transport:ride_detail", pk=pk)


@login_required
@require_POST
def join_request_decide(request, pk, join_id, action):
    jr = get_object_or_404(JoinRequest, pk=join_id, ride_id=pk)
    as_role = request.POST.get("as")  # organizer | admin
    as_organizer = True if as_role == "organizer" else (False if as_role == "admin" else None)
    try:
        services.decide_join_request(
            jr, request.user,
            as_organizer=as_organizer,
            approve=(action == "approve"),
            note=request.POST.get("note", ""),
        )
        messages.success(request, f"Join request {action}d.")
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect("transport:ride_detail", pk=pk)


# ---------------------------------------------------------------------------
# Phase 4 — GPS / live tracking
# ---------------------------------------------------------------------------

def _can_view_live_tracking(user) -> bool:
    return (
        user_has_permission(user, "view_live_tracking")
        or user_has_permission(user, "manage_transport")
        or getattr(user, "is_superuser", False)
    )


@login_required
@require_POST
def api_location_ping(request, pk):
    """Driver/manager posts GPS sample for an active ride."""
    import json

    ride = get_object_or_404(
        Ride.objects.select_related("vehicle").prefetch_related("stops", "passengers__stop", "passengers__employee"),
        pk=pk,
    )
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    try:
        lat = float(payload["lat"])
        lng = float(payload["lng"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "lat and lng are required"}, status=400)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return JsonResponse({"error": "Invalid coordinates"}, status=400)

    speed = payload.get("speed_kmh")
    accuracy = payload.get("accuracy_m")
    try:
        speed_kmh = float(speed) if speed is not None and speed != "" else None
        accuracy_m = float(accuracy) if accuracy is not None and accuracy != "" else None
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid speed or accuracy"}, status=400)

    try:
        _ping, result = services.record_location_ping(
            ride,
            request.user,
            lat=lat,
            lng=lng,
            speed_kmh=speed_kmh,
            accuracy_m=accuracy_m,
            source=payload.get("source") or "driver_pwa",
        )
    except PermissionError as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(result)


@login_required
@require_GET
def api_live_positions(request):
    if not _can_view_live_tracking(request.user):
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse({"rides": services.live_map_payload()})


@login_required
def live_map(request):
    if not _can_view_live_tracking(request.user):
        messages.error(request, "You don't have permission to view live tracking.")
        return redirect("transport:hub")
    policy = TransportationPolicy.current()
    return render(request, "transport/live_map.html", {
        "rides_json": services.live_map_payload(),
        "geofence_radius": policy.geofence_radius_metres,
        "can_manage": user_has_permission(request.user, "manage_transport"),
        **_map_defaults(),
    })

