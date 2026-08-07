"""Attendance report CSV/Excel export."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.core.exports import build_export_response
from .models import AttendanceRecord


ATTENDANCE_EXPORT_HEADERS = [
    "employee_id",
    "employee_name",
    "department",
    "date",
    "check_in",
    "check_out",
    "worked_hours",
    "late_minutes",
    "status",
    "source",
    "manual_override",
    "notes",
]


def filter_attendance_records(request):
    from apps.employees.scoping import (
        can_view_all_employees,
        managed_department_ids,
        scoped_department_queryset,
        scoped_employee_queryset,
    )
    from apps.employees.models import Employee

    qs = AttendanceRecord.objects.select_related("employee__user", "employee__department")
    if not can_view_all_employees(request.user):
        dept_ids = managed_department_ids(request.user)
        qs = qs.filter(employee__department_id__in=dept_ids) if dept_ids else qs.none()

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
    if dept:
        allowed = scoped_department_queryset(request.user)
        if can_view_all_employees(request.user) or allowed.filter(pk=dept).exists():
            qs = qs.filter(employee__department_id=dept)

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    selected_employee = request.GET.get("employee")
    if selected_employee:
        visible_employees = scoped_employee_queryset(request.user, Employee.objects.all())
        if visible_employees.filter(pk=selected_employee).exists():
            qs = qs.filter(employee_id=selected_employee)

    return qs.order_by("-date", "employee__employee_id")


def attendance_to_row(record: AttendanceRecord) -> list:
    employee = record.employee
    return [
        employee.employee_id,
        employee.full_name,
        employee.department.name if employee.department else "",
        record.date.isoformat(),
        record.check_in.strftime("%Y-%m-%d %H:%M") if record.check_in else "",
        record.check_out.strftime("%Y-%m-%d %H:%M") if record.check_out else "",
        str(record.worked_hours),
        record.late_minutes,
        record.get_status_display(),
        record.get_source_display(),
        "Yes" if record.is_manual_override else "No",
        record.notes,
    ]


def export_attendance_response(request, fmt: str):
    records = filter_attendance_records(request)
    rows = [attendance_to_row(rec) for rec in records]
    return build_export_response("attendance_report", fmt, ATTENDANCE_EXPORT_HEADERS, rows)
