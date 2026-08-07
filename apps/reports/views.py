import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from apps.core.permissions import permission_required
from apps.employees.models import Employee, Department, EmploymentStatus
from apps.attendance.models import AttendanceRecord, AttendanceStatus
from apps.leave.models import LeaveRequest, LeaveStatus
from apps.payroll.models import Payslip
from .models import ReportDefinition, ReportType
from .builder import export_report, run_report


@login_required
@permission_required("view_reports")
def reports_hub(request):
    today = timezone.now().date()
    active = Employee.objects.filter(status=EmploymentStatus.ACTIVE)
    saved_reports = ReportDefinition.objects.filter(
        Q(created_by=request.user) | Q(is_shared=True)
    )[:20]
    return render(request, "reports/hub.html", {
        "total_employees": active.count(),
        "gender_data": json.dumps(list(active.values("gender").annotate(c=Count("id")))),
        "dept_data": json.dumps(list(
            Department.objects.annotate(c=Count("employees", filter=Q(employees__status=EmploymentStatus.ACTIVE))).values("name", "c")
        )),
        "pending_leave": LeaveRequest.objects.filter(status=LeaveStatus.PENDING).count(),
        "present_today": AttendanceRecord.objects.filter(
            date=today, status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]
        ).count(),
        "total_payroll": Payslip.objects.aggregate(total=Count("id"))["total"],
        "saved_reports": saved_reports,
        "report_types": ReportType.choices,
    })


@login_required
@permission_required("view_reports")
def report_builder(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        report_type = request.POST.get("report_type", "employees")
        if name:
            report = ReportDefinition.objects.create(
                name=name,
                report_type=report_type,
                description=request.POST.get("description", ""),
                filters={"status": request.POST.get("filter_status", "")},
                created_by=request.user,
                is_shared=request.POST.get("is_shared") == "on",
            )
            messages.success(request, f"Report '{name}' saved.")
            return redirect("reports:detail", pk=report.pk)
        messages.error(request, "Report name is required.")
    return render(request, "reports/builder.html", {"report_types": ReportType.choices})


@login_required
@permission_required("view_reports")
def report_detail(request, pk):
    report = get_object_or_404(ReportDefinition, pk=pk)
    headers, rows = run_report(report)
    return render(request, "reports/detail.html", {
        "report": report,
        "headers": headers,
        "rows": rows[:100],
        "total_rows": len(rows),
    })


@login_required
@permission_required("export_reports")
def report_export(request, pk):
    report = get_object_or_404(ReportDefinition, pk=pk)
    fmt = request.GET.get("format", "csv")
    if fmt not in ("csv", "xlsx", "pdf", "docx"):
        fmt = "csv"
    return export_report(report, fmt)
