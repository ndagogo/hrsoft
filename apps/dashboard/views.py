import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Avg, Q
from django.shortcuts import render
from django.utils import timezone

from apps.employees.models import Employee, Department, EmploymentStatus
from apps.attendance.models import AttendanceRecord, AttendanceStatus, BiometricDevice, RawPunchLog
from apps.leave.models import LeaveRequest, LeaveStatus
from apps.payroll.models import PayrollPeriod, Payslip, PayrollStatus
from apps.announcements.models import Announcement
from apps.recruitment.models import Vacancy, VacancyStatus


@login_required
def router(request):
    """Routes the logged-in user to the dashboard matching their role's dashboard_key."""
    key = request.user.dashboard_key
    view_map = {
        "admin": admin_dashboard,
        "hr": hr_dashboard,
        "manager": manager_dashboard,
        "payroll": payroll_dashboard,
        "employee": employee_dashboard,
    }
    view = view_map.get(key, employee_dashboard)
    return view(request)


def _last_n_days(n):
    today = timezone.now().date()
    return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]


def _attendance_trend(days=14, department=None):
    qs = AttendanceRecord.objects.all()
    if department:
        qs = qs.filter(employee__department=department)
    labels, present_series, late_series, absent_series = [], [], [], []
    for day in _last_n_days(days):
        day_qs = qs.filter(date=day)
        labels.append(day.strftime("%b %d"))
        present_series.append(day_qs.filter(status=AttendanceStatus.PRESENT).count())
        late_series.append(day_qs.filter(status=AttendanceStatus.LATE).count())
        absent_series.append(day_qs.filter(status=AttendanceStatus.ABSENT).count())
    return labels, present_series, late_series, absent_series


@login_required
def admin_dashboard(request):
    today = timezone.now().date()

    total_employees = Employee.objects.filter(status=EmploymentStatus.ACTIVE).count()
    total_departments = Department.objects.count()
    pending_leave = LeaveRequest.objects.filter(status=LeaveStatus.PENDING).count()
    active_devices = BiometricDevice.objects.filter(is_active=True).count()

    today_attendance = AttendanceRecord.objects.filter(date=today)
    present_today = today_attendance.filter(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]).count()
    attendance_rate = round((present_today / total_employees) * 100, 1) if total_employees else 0

    dept_breakdown = (
        Department.objects.annotate(count=Count("employees", filter=Q(employees__status=EmploymentStatus.ACTIVE)))
        .values("name", "count").order_by("-count")
    )

    labels, present_series, late_series, absent_series = _attendance_trend(14)

    role_breakdown = (
        Employee.objects.filter(status=EmploymentStatus.ACTIVE)
        .values("user__role__name").annotate(count=Count("id")).order_by("-count")
    )

    recent_punches = RawPunchLog.objects.select_related("employee__user", "device").order_by("-timestamp")[:8]
    recent_leave = LeaveRequest.objects.select_related("employee__user").order_by("-created_at")[:6]

    # Upcoming birthdays (next 30 days)
    upcoming_birthdays = []
    for emp in Employee.objects.filter(status=EmploymentStatus.ACTIVE, date_of_birth__isnull=False).select_related("user")[:200]:
        if emp.date_of_birth:
            bday = emp.date_of_birth.replace(year=today.year)
            if bday < today:
                bday = bday.replace(year=today.year + 1)
            if (bday - today).days <= 30:
                upcoming_birthdays.append(emp)
    upcoming_birthdays = sorted(upcoming_birthdays, key=lambda e: e.date_of_birth.replace(year=today.year if e.date_of_birth.replace(year=today.year) >= today else today.year + 1))[:6]

    expiring_contracts = Employee.objects.filter(
        status=EmploymentStatus.ACTIVE, contract_end__isnull=False,
        contract_end__lte=today + timedelta(days=30), contract_end__gte=today,
    ).select_related("user", "department")[:6]

    open_vacancies = Vacancy.objects.filter(status=VacancyStatus.OPEN).count()
    open_positions = (
        Vacancy.objects.filter(status=VacancyStatus.OPEN).aggregate(total=Sum("positions"))["total"] or 0
    )
    announcements = (
        Announcement.objects.visible_to(request.user)
        .select_related("author")
        .prefetch_related("departments", "branches", "cadres")
        .order_by("-published_at")[:4]
    )

    gender_dist = list(Employee.objects.filter(status=EmploymentStatus.ACTIVE).values("gender").annotate(count=Count("id")))

    context = {
        "total_employees": total_employees,
        "total_departments": total_departments,
        "pending_leave": pending_leave,
        "active_devices": active_devices,
        "attendance_rate": attendance_rate,
        "present_today": present_today,
        "dept_labels": json.dumps([d["name"] for d in dept_breakdown]),
        "dept_counts": json.dumps([d["count"] for d in dept_breakdown]),
        "trend_labels": json.dumps(labels),
        "trend_present": json.dumps(present_series),
        "trend_late": json.dumps(late_series),
        "trend_absent": json.dumps(absent_series),
        "role_labels": json.dumps([r["user__role__name"] or "Unassigned" for r in role_breakdown]),
        "role_counts": json.dumps([r["count"] for r in role_breakdown]),
        "recent_punches": recent_punches,
        "recent_leave": recent_leave,
        "upcoming_birthdays": upcoming_birthdays,
        "expiring_contracts": expiring_contracts,
        "open_vacancies": open_vacancies,
        "open_positions": open_positions,
        "announcements": announcements,
        "gender_labels": json.dumps([{"M": "Male", "F": "Female", "O": "Other"}.get(g["gender"] or "", "Unknown") for g in gender_dist]),
        "gender_counts": json.dumps([g["count"] for g in gender_dist]),
    }
    return render(request, "dashboard/admin_dashboard.html", context)


@login_required
def hr_dashboard(request):
    today = timezone.now().date()

    total_employees = Employee.objects.filter(status=EmploymentStatus.ACTIVE).count()
    new_hires_30d = Employee.objects.filter(date_joined__gte=today - timedelta(days=30)).count()
    pending_leave = LeaveRequest.objects.filter(status=LeaveStatus.PENDING).count()
    on_leave_today = AttendanceRecord.objects.filter(date=today, status=AttendanceStatus.ON_LEAVE).count()
    open_vacancies = Vacancy.objects.filter(status=VacancyStatus.OPEN).count()

    leave_by_type = (
        LeaveRequest.objects.filter(status=LeaveStatus.APPROVED)
        .values("leave_type__name").annotate(count=Count("id")).order_by("-count")
    )

    labels, present_series, late_series, absent_series = _attendance_trend(14)

    upcoming_leave = LeaveRequest.objects.select_related("employee__user").filter(
        status=LeaveStatus.APPROVED, start_date__gte=today
    ).order_by("start_date")[:6]

    pending_requests = LeaveRequest.objects.select_related("employee__user", "leave_type").filter(
        status=LeaveStatus.PENDING
    ).order_by("created_at")[:8]

    headcount_by_dept = Department.objects.annotate(
        count=Count("employees", filter=Q(employees__status=EmploymentStatus.ACTIVE))
    ).order_by("-count")

    context = {
        "total_employees": total_employees,
        "new_hires_30d": new_hires_30d,
        "pending_leave": pending_leave,
        "on_leave_today": on_leave_today,
        "open_vacancies": open_vacancies,
        "leave_labels": json.dumps([l["leave_type__name"] for l in leave_by_type]),
        "leave_counts": json.dumps([l["count"] for l in leave_by_type]),
        "trend_labels": json.dumps(labels),
        "trend_present": json.dumps(present_series),
        "trend_late": json.dumps(late_series),
        "trend_absent": json.dumps(absent_series),
        "upcoming_leave": upcoming_leave,
        "pending_requests": pending_requests,
        "headcount_by_dept": headcount_by_dept,
    }
    return render(request, "dashboard/hr_dashboard.html", context)


@login_required
def manager_dashboard(request):
    employee = getattr(request.user, "employee_profile", None)
    department = employee.department if employee else None
    today = timezone.now().date()

    team = Employee.objects.filter(department=department, status=EmploymentStatus.ACTIVE) if department else Employee.objects.none()
    team_count = team.count()

    today_attendance = AttendanceRecord.objects.filter(employee__in=team, date=today)
    present_today = today_attendance.filter(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]).count()
    late_today = today_attendance.filter(status=AttendanceStatus.LATE).count()
    absent_today = max(0, team_count - today_attendance.count())

    pending_leave = LeaveRequest.objects.filter(employee__in=team, status=LeaveStatus.PENDING).count()

    labels, present_series, late_series, absent_series = _attendance_trend(14, department=department)

    team_members = team.select_related("user", "designation").order_by("user__first_name")
    pending_requests = LeaveRequest.objects.select_related("employee__user", "leave_type").filter(
        employee__in=team, status=LeaveStatus.PENDING
    ).order_by("created_at")[:8]

    context = {
        "department": department,
        "team_count": team_count,
        "present_today": present_today,
        "late_today": late_today,
        "absent_today": absent_today,
        "pending_leave": pending_leave,
        "trend_labels": json.dumps(labels),
        "trend_present": json.dumps(present_series),
        "trend_late": json.dumps(late_series),
        "trend_absent": json.dumps(absent_series),
        "team_members": team_members,
        "pending_requests": pending_requests,
    }
    return render(request, "dashboard/manager_dashboard.html", context)


@login_required
def payroll_dashboard(request):
    latest_periods = PayrollPeriod.objects.all()[:6]
    current_period = (
        PayrollPeriod.objects.filter(status__in=[PayrollStatus.PROCESSED, PayrollStatus.PAID]).first()
        or PayrollPeriod.objects.first()
    )

    total_payroll_cost = Payslip.objects.filter(period=current_period).aggregate(total=Sum("net_pay"))["total"] or 0 if current_period else 0

    cost_trend = []
    cost_labels = []
    for period in PayrollPeriod.objects.order_by("start_date")[:12]:
        cost_labels.append(period.name)
        cost_trend.append(float(period.total_net_pay))

    dept_cost = (
        Payslip.objects.filter(period=current_period)
        .values("employee__department__name").annotate(total=Sum("net_pay")).order_by("-total")
    ) if current_period else []

    pending_payslip_count = Payslip.objects.filter(period=current_period).count() if current_period else 0
    avg_net_pay = Payslip.objects.filter(period=current_period).aggregate(avg=Avg("net_pay"))["avg"] or 0 if current_period else 0

    context = {
        "latest_periods": latest_periods,
        "current_period": current_period,
        "total_payroll_cost": total_payroll_cost,
        "avg_net_pay": avg_net_pay,
        "pending_payslip_count": pending_payslip_count,
        "cost_labels": json.dumps(cost_labels),
        "cost_trend": json.dumps(cost_trend),
        "dept_cost_labels": json.dumps([d["employee__department__name"] or "Unassigned" for d in dept_cost]),
        "dept_cost_values": json.dumps([float(d["total"]) for d in dept_cost]),
    }
    return render(request, "dashboard/payroll_dashboard.html", context)


@login_required
def employee_dashboard(request):
    employee = getattr(request.user, "employee_profile", None)
    today = timezone.now().date()

    if not employee:
        return render(request, "dashboard/employee_dashboard.html", {"employee": None})

    month_records = employee.attendance_records.filter(date__month=today.month, date__year=today.year)
    present_days = month_records.filter(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]).count()
    late_days = month_records.filter(status=AttendanceStatus.LATE).count()

    today_record = employee.attendance_records.filter(date=today).first()
    pending_leave = employee.leave_requests.filter(status=LeaveStatus.PENDING).count()

    labels, present_series, late_series, absent_series = [], [], [], []
    for day in _last_n_days(14):
        rec = employee.attendance_records.filter(date=day).first()
        labels.append(day.strftime("%b %d"))
        present_series.append(1 if rec and rec.status in [AttendanceStatus.PRESENT, AttendanceStatus.LATE] else 0)
        late_series.append(1 if rec and rec.status == AttendanceStatus.LATE else 0)
        absent_series.append(1 if not rec or rec.status == AttendanceStatus.ABSENT else 0)

    recent_payslip = employee.payslips.order_by("-period__start_date").first()
    recent_leave = employee.leave_requests.order_by("-created_at")[:5]

    context = {
        "employee": employee,
        "present_days": present_days,
        "late_days": late_days,
        "today_record": today_record,
        "pending_leave": pending_leave,
        "leave_balance": employee.leave_balance_days,
        "trend_labels": json.dumps(labels),
        "trend_present": json.dumps(present_series),
        "trend_late": json.dumps(late_series),
        "trend_absent": json.dumps(absent_series),
        "recent_payslip": recent_payslip,
        "recent_leave": recent_leave,
    }
    return render(request, "dashboard/employee_dashboard.html", context)
