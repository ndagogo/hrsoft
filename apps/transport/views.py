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
    DriverForm,
    JoinRequestForm,
    ReviewForm,
    RideRequestForm,
    ShuttleRideForm,
    VehicleDocumentForm,
    VehicleForm,
    make_shuttle_passenger_formset,
)
from .models import (
    Driver,
    JoinRequest,
    JoinRequestStatus,
    Ride,
    RideApprovalStep,
    RideEvent,
    RideEventType,
    RidePassenger,
    RideStatus,
    RideType,
    StepStatus,
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
    emp = _employee_or_none(request.user)
    driver = _driver_or_none(request.user)

    my_rides = Ride.objects.none()
    if emp:
        my_rides = (
            Ride.objects.filter(Q(requester=emp) | Q(passengers__employee=emp))
            .distinct()
            .select_related("vehicle", "driver__employee__user")
            .order_by("-scheduled_departure")[:10]
        )

    open_carpools = Ride.objects.filter(
        allow_carpool=True,
        status__in=[
            RideStatus.APPROVED, RideStatus.DRIVER_PENDING, RideStatus.DRIVER_ACCEPTED,
            RideStatus.READY, RideStatus.PENDING_APPROVAL,
        ],
    ).select_related("vehicle", "driver__employee__user").annotate(
        pax=Count("passengers")
    ).order_by("scheduled_departure")[:12]

    stats = {}
    if can_view or can_manage:
        stats = {
            "vehicles": Vehicle.objects.filter(is_active=True).count(),
            "drivers": Driver.objects.filter(status="active").count(),
            "active_rides": Ride.objects.filter(
                status__in=services.ACTIVE_RIDE_STATUSES
            ).count(),
            "pending_approvals": Ride.objects.filter(status=RideStatus.PENDING_APPROVAL).count(),
        }

    return render(request, "transport/hub.html", {
        "can_manage": can_manage,
        "can_view": can_view or can_manage,
        "can_history": can_history,
        "can_create": user_has_permission(request.user, "create_ride") or can_manage,
        "can_approve": user_has_permission(request.user, "approve_transport") or can_manage,
        "is_driver": bool(driver),
        "my_rides": my_rides,
        "open_carpools": open_carpools,
        "stats": stats,
        "employee": emp,
    })


@login_required
@permission_required("view_transport")
def vehicle_list(request):
    vehicles = Vehicle.objects.select_related("branch").all()
    return render(request, "transport/vehicles.html", {
        "vehicles": vehicles,
        "can_manage": user_has_permission(request.user, "manage_transport"),
        "form": VehicleForm() if user_has_permission(request.user, "manage_transport") else None,
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
    vehicle = get_object_or_404(Vehicle.objects.prefetch_related("documents", "rides"), pk=pk)
    return render(request, "transport/vehicle_detail.html", {
        "vehicle": vehicle,
        "can_manage": user_has_permission(request.user, "manage_transport"),
        "doc_form": VehicleDocumentForm() if user_has_permission(request.user, "manage_transport") else None,
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
    can_view_all = can_manage or user_has_permission(request.user, "view_transport")
    emp = _employee_or_none(request.user)
    qs = Ride.objects.select_related("vehicle", "driver__employee__user", "requester__user", "organizer")
    if can_view_all:
        rides = qs.all()[:100]
    elif emp:
        rides = qs.filter(Q(requester=emp) | Q(passengers__employee=emp) | Q(organizer=request.user)).distinct()[:50]
    else:
        rides = qs.filter(organizer=request.user)[:50]
    return render(request, "transport/rides.html", {
        "rides": rides,
        "can_create": user_has_permission(request.user, "create_ride") or can_manage,
        "can_manage": can_manage,
    })


def _can_view_transport_history(user) -> bool:
    return (
        user_has_permission(user, "view_transport")
        or user_has_permission(user, "manage_transport")
        or user_has_permission(user, "approve_transport")
        or getattr(user, "is_superuser", False)
    )


@login_required
def transport_history(request):
    """
    Full transport management history: all ride requests, approval decisions,
    and operational status events across the module.
    """
    if not _can_view_transport_history(request.user):
        messages.error(request, "You don't have permission to view transport history.")
        return redirect("transport:hub")

    tab = (request.GET.get("tab") or "requests").strip().lower()
    if tab not in {"requests", "approvals", "activity"}:
        tab = "requests"

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    ride_type = (request.GET.get("ride_type") or "").strip()
    event_type = (request.GET.get("event_type") or "").strip()
    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")

    rides_qs = Ride.objects.select_related(
        "vehicle", "driver__employee__user", "requester__user", "organizer",
    ).prefetch_related("passengers", "approval_steps")

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

    events_qs = RideEvent.objects.select_related(
        "ride", "ride__vehicle", "actor", "passenger__employee__user",
    ).order_by("-created_at")
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

    status_counts = {
        row["status"]: row["c"]
        for row in Ride.objects.values("status").annotate(c=Count("id"))
    }
    stats = {
        "total_rides": Ride.objects.count(),
        "pending": status_counts.get(RideStatus.PENDING_APPROVAL, 0),
        "active": Ride.objects.filter(status__in=services.ACTIVE_RIDE_STATUSES).count(),
        "completed": status_counts.get(RideStatus.COMPLETED, 0),
        "rejected": status_counts.get(RideStatus.REJECTED, 0),
        "cancelled": (
            status_counts.get(RideStatus.CANCELLED, 0)
            + status_counts.get(RideStatus.ABORTED, 0)
        ),
        "events": RideEvent.objects.count(),
        "approval_decisions": RideApprovalStep.objects.filter(
            status__in=[StepStatus.APPROVED, StepStatus.REJECTED]
        ).count(),
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
    })


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

    return render(request, "transport/ride_form.html", {"form": form, **_map_defaults()})


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

    if not (can_manage or is_organizer or is_passenger or is_requester or is_assigned_driver
            or user_has_permission(request.user, "view_transport")
            or user_has_permission(request.user, "approve_transport")):
        messages.error(request, "You cannot view this ride.")
        return redirect("transport:hub")

    return render(request, "transport/ride_detail.html", {
        "ride": ride,
        "events": ride.events.select_related("actor", "passenger__employee__user")[:80],
        "can_manage": can_manage,
        "can_review": services.user_can_review_ride(request.user, ride),
        "can_submit": ride.status == RideStatus.DRAFT and (is_organizer or is_requester or can_manage),
        "can_accept_driver": ride.status == RideStatus.DRIVER_PENDING and (is_assigned_driver or can_manage),
        "can_start": ride.status in (RideStatus.READY, RideStatus.DRIVER_ACCEPTED) and (
            is_assigned_driver or can_manage
        ),
        "can_complete": ride.status == RideStatus.IN_PROGRESS and (is_assigned_driver or can_manage),
        "can_join": (
            emp and ride.allow_carpool
            and not is_passenger
            and ride.status in (
                RideStatus.APPROVED, RideStatus.DRIVER_PENDING, RideStatus.DRIVER_ACCEPTED,
                RideStatus.READY, RideStatus.PENDING_APPROVAL,
            )
        ),
        "is_organizer": is_organizer,
        "join_form": JoinRequestForm(),
        "review_form": ReviewForm(),
        "pending_joins": ride.join_requests.filter(
            status__in=[
                JoinRequestStatus.PENDING,
                JoinRequestStatus.ORGANIZER_APPROVED,
                JoinRequestStatus.ADMIN_APPROVED,
            ]
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
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("transport:ride_detail", pk=pk)


@login_required
def approvals(request):
    pending = services.pending_approvals_for_user(request.user)
    return render(request, "transport/approvals.html", {
        "pending": pending,
        "review_form": ReviewForm(),
    })


@login_required
@require_POST
def ride_review(request, pk, action):
    ride = get_object_or_404(Ride, pk=pk)
    note = request.POST.get("note", "")
    try:
        services.process_approval(ride, request.user, "approve" if action == "approve" else "reject", note)
        messages.success(request, f"Ride {action}d.")
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
    qs = Ride.objects.select_related("vehicle", "requester__user").prefetch_related("passengers__employee__user")
    if driver:
        assigned = qs.filter(driver=driver).exclude(
            status__in=[RideStatus.COMPLETED, RideStatus.CANCELLED, RideStatus.REJECTED, RideStatus.ABORTED, RideStatus.DRAFT]
        ).order_by("scheduled_departure")
    else:
        assigned = qs.filter(status__in=services.ACTIVE_RIDE_STATUSES).order_by("scheduled_departure")[:20]
    return render(request, "transport/driver_portal.html", {
        "driver": driver,
        "assigned": assigned,
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
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(request.POST.get("next") or f"/transport/rides/{pk}/")


@login_required
@require_POST
def ride_complete(request, pk):
    ride = get_object_or_404(Ride, pk=pk)
    try:
        services.complete_ride(ride, request.user)
        messages.success(request, "Ride completed.")
    except ValueError as exc:
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
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("transport:ride_detail", pk=pk)


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
        services.request_to_join(ride, emp, form.cleaned_data["destination_label"])
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
