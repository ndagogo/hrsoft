"""Calendar event feeds for FullCalendar widgets."""

import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone

from apps.leave.models import LeaveRequest, LeaveStatus
from apps.attendance.models import AttendanceRecord, AttendanceStatus


@login_required
def calendar_events(request):
    start = request.GET.get("start", "")[:10]
    end = request.GET.get("end", "")[:10]
    scope = request.GET.get("scope", "personal")

    events = []
    today = timezone.now().date()

    if scope == "personal":
        employee = getattr(request.user, "employee_profile", None)
        if employee:
            leave_qs = employee.leave_requests.filter(status=LeaveStatus.APPROVED)
            if start:
                leave_qs = leave_qs.filter(end_date__gte=start)
            if end:
                leave_qs = leave_qs.filter(start_date__lte=end)
            for lr in leave_qs:
                stand_in = lr.stand_in_employee.full_name if lr.stand_in_employee else ""
                title = f"Leave: {lr.leave_type.name}"
                if stand_in:
                    title += f" (Stand-in: {stand_in})"
                events.append({
                    "title": title,
                    "start": lr.start_date.isoformat(),
                    "end": (lr.end_date + timedelta(days=1)).isoformat(),
                    "color": lr.leave_type.color or "#8b5cf6",
                    "extendedProps": {"type": "leave", "stand_in": stand_in},
                })
            att_qs = employee.attendance_records.all()
            if start:
                att_qs = att_qs.filter(date__gte=start)
            if end:
                att_qs = att_qs.filter(date__lte=end)
            color_map = {
                AttendanceStatus.PRESENT: "#22c55e",
                AttendanceStatus.LATE: "#f5a524",
                AttendanceStatus.ABSENT: "#f43f5e",
                AttendanceStatus.ON_LEAVE: "#8b5cf6",
            }
            for rec in att_qs[:60]:
                events.append({
                    "title": rec.get_status_display(),
                    "start": rec.date.isoformat(),
                    "color": color_map.get(rec.status, "#64748b"),
                    "extendedProps": {"type": "attendance"},
                })
    else:
        from apps.core.permissions import user_has_permission
        if user_has_permission(request.user, "view_leave") or user_has_permission(request.user, "approve_leave"):
            leave_qs = LeaveRequest.objects.filter(status=LeaveStatus.APPROVED).select_related(
                "employee__user", "leave_type", "stand_in_employee__user",
            )
            if start:
                leave_qs = leave_qs.filter(end_date__gte=start)
            if end:
                leave_qs = leave_qs.filter(start_date__lte=end)
            for lr in leave_qs[:100]:
                stand_in = lr.stand_in_employee.full_name if lr.stand_in_employee else ""
                title = f"{lr.employee.full_name}: {lr.leave_type.name}"
                if stand_in:
                    title += f" · Stand-in: {stand_in}"
                events.append({
                    "title": title,
                    "start": lr.start_date.isoformat(),
                    "end": (lr.end_date + timedelta(days=1)).isoformat(),
                    "color": "#8b5cf6",
                    "extendedProps": {"type": "leave", "stand_in": stand_in},
                })

    return JsonResponse(events, safe=False)
