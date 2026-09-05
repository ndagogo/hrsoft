import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from datetime import timedelta

from django.db.models import Count, Q, Avg, Sum
from django.template.loader import render_to_string
from django.http import JsonResponse

from apps.core.permissions import permission_required
from apps.employees.models import Employee
from .export import export_attendance_response
from .models import AttendanceRecord, BiometricDevice, RawPunchLog, AttendanceStatus
from .forms import BiometricDeviceForm, AttendanceOverrideForm
from .biometrics import recompute_daily_attendance


@login_required
@permission_required("view_attendance")
def attendance_list(request):
    from apps.employees.scoping import (
        can_view_all_employees,
        managed_department_ids,
        scoped_department_queryset,
        scoped_employee_queryset,
    )

    qs = AttendanceRecord.objects.select_related("employee__user", "employee__department")
    org_wide = can_view_all_employees(request.user)
    if not org_wide:
        dept_ids = managed_department_ids(request.user)
        qs = qs.filter(employee__department_id__in=dept_ids) if dept_ids else qs.none()
    visible_employees = scoped_employee_queryset(
        request.user,
        Employee.objects.select_related("user", "department").order_by("user__first_name", "employee_id"),
    )

    period = request.GET.get("period", "").strip()
    today = timezone.localdate()
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    if period == "today":
        date_from = today.isoformat()
        date_to = today.isoformat()
    elif period == "last_7":
        date_from = (today - timedelta(days=6)).isoformat()
        date_to = today.isoformat()
    elif period == "last_30":
        date_from = (today - timedelta(days=29)).isoformat()
        date_to = today.isoformat()
    elif period == "this_month":
        date_from = today.replace(day=1).isoformat()
        date_to = today.isoformat()
    elif period == "last_month":
        this_month_start = today.replace(day=1)
        last_month_end = this_month_start - timedelta(days=1)
        date_from = last_month_end.replace(day=1).isoformat()
        date_to = last_month_end.isoformat()

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if not date_from and not date_to:
        qs = qs.filter(date=today)

    dept = request.GET.get("department")
    departments = scoped_department_queryset(request.user)
    if dept:
        if org_wide or departments.filter(pk=dept).exists():
            qs = qs.filter(employee__department_id=dept)
        else:
            dept = ""

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    selected_employee = request.GET.get("employee")
    if selected_employee:
        if visible_employees.filter(pk=selected_employee).exists():
            qs = qs.filter(employee_id=selected_employee)
        else:
            selected_employee = ""

    summary_qs = qs
    qs = qs.order_by("-date", "employee__employee_id")
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    stats = summary_qs.aggregate(
        present=Count("id", filter=Q(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE])),
        late=Count("id", filter=Q(status=AttendanceStatus.LATE)),
        absent=Count("id", filter=Q(status=AttendanceStatus.ABSENT)),
        avg_hours=Avg("worked_hours"),
        total_hours=Sum("worked_hours"),
        total_records=Count("id"),
        staff_count=Count("employee_id", distinct=True),
        on_time=Count("id", filter=Q(status=AttendanceStatus.PRESENT)),
    )
    total_records = stats["total_records"] or 0
    stats["attendance_rate"] = round(((stats["present"] or 0) / total_records) * 100, 1) if total_records else 0
    stats["late_rate"] = round(((stats["late"] or 0) / total_records) * 100, 1) if total_records else 0

    employee_summary = (
        summary_qs.values("employee_id", "employee__employee_id", "employee__user__first_name", "employee__user__last_name")
        .annotate(
            present_days=Count("id", filter=Q(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE])),
            late_days=Count("id", filter=Q(status=AttendanceStatus.LATE)),
            absent_days=Count("id", filter=Q(status=AttendanceStatus.ABSENT)),
            total_hours=Sum("worked_hours"),
            avg_hours=Avg("worked_hours"),
        )
        .order_by("-present_days", "employee__employee_id")[:50]
    )

    filter_params = request.GET.copy()
    if "page" in filter_params:
        filter_params.pop("page")

    return render(request, "attendance/list.html", {
        "page_obj": page_obj,
        "departments": departments,
        "employees": visible_employees[:1000],
        "employee_summary": employee_summary,
        "stats": stats,
        "date_from": date_from or "",
        "date_to": date_to or "",
        "selected_period": period,
        "selected_department": dept or "",
        "selected_employee": selected_employee or "",
        "selected_status": status or "",
        "status_choices": AttendanceStatus.choices,
        "filter_query": filter_params.urlencode(),
        "org_wide_directory": org_wide,
    })


@login_required
@permission_required("view_attendance")
def attendance_export(request):
    fmt = request.GET.get("format", "csv")
    if fmt not in ("csv", "xlsx"):
        fmt = "csv"
    return export_attendance_response(request, fmt)


@login_required
def my_attendance(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.warning(request, "No employee profile linked to your account yet.")
        return redirect("dashboard:router")

    records = employee.attendance_records.order_by("-date")[:31]
    raw_logs = employee.punch_logs.order_by("-timestamp")[:15]

    month_records = employee.attendance_records.filter(date__month=timezone.now().month, date__year=timezone.now().year)
    summary = month_records.aggregate(
        present_days=Count("id", filter=Q(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE])),
        late_days=Count("id", filter=Q(status=AttendanceStatus.LATE)),
        absent_days=Count("id", filter=Q(status=AttendanceStatus.ABSENT)),
    )

    return render(request, "attendance/my_attendance.html", {
        "employee": employee, "records": records, "raw_logs": raw_logs, "summary": summary,
    })


@login_required
@permission_required("manage_attendance")
def attendance_override(request, pk):
    record = get_object_or_404(AttendanceRecord, pk=pk)
    if request.method == "POST":
        form = AttendanceOverrideForm(request.POST, instance=record)
        if form.is_valid():
            record = form.save(commit=False)
            record.is_manual_override = True
            record.overridden_by = request.user
            record.save()
            messages.success(request, "Attendance record updated manually.")
            return redirect("attendance:list")
    else:
        form = AttendanceOverrideForm(instance=record)

    html = render_to_string("attendance/_override_modal_body.html", {"form": form, "record": record}, request=request)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("modal"):
        return JsonResponse({"html": html})
    return render(request, "attendance/override_page.html", {"form": form, "record": record})


# --- Biometric device administration ---------------------------------------

@login_required
@permission_required("manage_devices")
def device_list(request):
    devices = list(BiometricDevice.objects.all())
    for device in devices:
        device.edit_form = BiometricDeviceForm(instance=device, prefix=f"device_{device.pk}")
    recent_logs = RawPunchLog.objects.select_related("device", "employee__user").order_by("-timestamp")[:25]
    unmatched_ids = list(
        RawPunchLog.objects.filter(matched=False)
        .exclude(device_employee_no="")
        .values_list("device_employee_no", flat=True)
        .distinct()[:40]
    )
    form = BiometricDeviceForm(prefix="new")
    return render(request, "attendance/devices.html", {
        "devices": devices,
        "recent_logs": recent_logs,
        "form": form,
        "unmatched_ids": unmatched_ids,
        "employees": Employee.objects.select_related("user").filter(status="active").order_by("employee_id")[:500],
    })


@login_required
@permission_required("manage_devices")
def link_biometric_id(request):
    """
    Map a ZKTeco/HikVision device User ID to an HRMS employee, then rematch
    existing unmatched punches for that ID.
    """
    if request.method != "POST":
        return redirect("attendance:devices")

    device_user_id = (request.POST.get("device_employee_no") or "").strip()
    employee_pk = request.POST.get("employee_id")
    if not device_user_id or not employee_pk:
        messages.error(request, "Select both a device User ID and an employee.")
        return redirect("attendance:devices")

    employee = get_object_or_404(Employee, pk=employee_pk)
    conflict = Employee.objects.filter(biometric_id=device_user_id).exclude(pk=employee.pk).first()
    if conflict:
        messages.error(
            request,
            f"Device User ID {device_user_id} is already linked to {conflict.full_name}.",
        )
        return redirect("attendance:devices")

    employee.biometric_id = device_user_id
    employee.biometric_enrolled = True
    employee.save(update_fields=["biometric_id", "biometric_enrolled", "updated_at"])

    logs = list(RawPunchLog.objects.filter(device_employee_no=device_user_id, matched=False))
    days = set()
    for log in logs:
        log.employee = employee
        log.matched = True
        log.save(update_fields=["employee", "matched"])
        days.add(log.timestamp.date())

    for day in days:
        recompute_daily_attendance(employee, day)

    messages.success(
        request,
        f"Linked device User ID {device_user_id} to {employee.full_name}. Rematched {len(logs)} punch(es).",
    )
    return redirect("attendance:devices")


@login_required
@permission_required("manage_devices")
def device_create(request):
    if request.method == "POST":
        form = BiometricDeviceForm(request.POST, prefix="new")
        if form.is_valid():
            device = form.save(commit=False)
            if not device.webhook_token:
                device.webhook_token = secrets.token_hex(16)
            device.save()
            messages.success(request, f"Device '{device.name}' registered. Webhook token: {device.webhook_token}")
        else:
            messages.error(request, "Could not register device. Check required fields (name, IP for pull mode).")
    return redirect("attendance:devices")


@login_required
@permission_required("manage_devices")
def device_edit(request, pk):
    device = get_object_or_404(BiometricDevice, pk=pk)
    prefix = f"device_{pk}"
    if request.method == "POST":
        form = BiometricDeviceForm(request.POST, instance=device, prefix=prefix)
        if form.is_valid():
            form.save()
            messages.success(request, "Device updated.")
        else:
            # Surface the first field error so blank/default overwrites are obvious
            first_error = next(iter(form.errors.values()), ["Invalid data."])[0]
            messages.error(request, f"Could not update device: {first_error}")
    return redirect("attendance:devices")


@login_required
@permission_required("manage_devices")
def device_delete(request, pk):
    device = get_object_or_404(BiometricDevice, pk=pk)
    if request.method == "POST":
        device.delete()
        messages.success(request, "Device removed.")
    return redirect("attendance:devices")
