from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.template.loader import render_to_string
from django.http import JsonResponse

from apps.core.permissions import permission_required
from apps.core.audit import log_change, serialize_instance
from apps.employees.models import Employee
from apps.attendance.models import AttendanceRecord, AttendanceStatus
from apps.notifications.services import deliver_notification
from .models import PayrollPeriod, Payslip, PayrollStatus, PayrollApprovalStatus
from .forms import PayrollPeriodForm, PayslipAdjustmentForm
from .exports import payslip_pdf_response, bank_schedule_response


TAX_RATE = Decimal("0.075")
PENSION_RATE = Decimal("0.08")
LATE_PENALTY_PER_INSTANCE = Decimal("1000")


def _notify_payroll_stakeholders(period, title, message):
    from apps.accounts.models import User
    from apps.rbac.models import Permission
    perm = Permission.objects.filter(codename="manage_payroll").first()
    if not perm:
        return
    for user in User.objects.filter(role__permissions=perm, is_active=True).distinct()[:10]:
        deliver_notification(user, title, message, category="payroll", link=f"/payroll/periods/{period.pk}/")


@login_required
@permission_required("view_payroll")
def payroll_period_list(request):
    periods = PayrollPeriod.objects.all()
    form = PayrollPeriodForm()
    if request.method == "POST":
        form = PayrollPeriodForm(request.POST)
        if form.is_valid():
            period = form.save()
            messages.success(request, f"Payroll period '{period.name}' created.")
            return redirect("payroll:periods")
        else:
            messages.error(request, "Please fix the errors below.")
    return render(request, "payroll/periods.html", {"periods": periods, "form": form})


@login_required
@permission_required("manage_payroll")
def run_payroll(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    if not period.can_run:
        messages.error(request, "This payroll period is locked or pending approval and cannot be re-run.")
        return redirect("payroll:period_detail", pk=pk)

    old = serialize_instance(period)
    employees = Employee.objects.filter(status="active").select_related("user")
    created_count = 0

    for employee in employees:
        records = AttendanceRecord.objects.filter(
            employee=employee, date__gte=period.start_date, date__lte=period.end_date
        )
        days_present = records.filter(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]).count()
        days_late = records.filter(status=AttendanceStatus.LATE).count()
        days_absent = records.filter(status=AttendanceStatus.ABSENT).count()

        basic = employee.basic_salary
        housing = basic * Decimal("0.15")
        transport = basic * Decimal("0.10")
        tax = basic * TAX_RATE
        pension = basic * PENSION_RATE
        late_penalty = Decimal(days_late) * LATE_PENALTY_PER_INSTANCE

        payslip, _ = Payslip.objects.update_or_create(
            period=period,
            employee=employee,
            defaults=dict(
                basic_salary=basic,
                housing_allowance=housing,
                transport_allowance=transport,
                other_allowance=0,
                tax_deduction=tax,
                pension_deduction=pension,
                other_deduction=0,
                late_penalty_deduction=late_penalty,
                days_present=days_present,
                days_absent=days_absent,
                days_late=days_late,
            ),
        )
        payslip.compute()
        created_count += 1

    period.status = PayrollStatus.PROCESSED
    period.approval_status = PayrollApprovalStatus.NOT_SUBMITTED
    period.processed_by = request.user
    period.processed_at = timezone.now()
    period.save()

    log_change(request, "payroll_run", instance=period, old_data=old, new_data=serialize_instance(period))
    messages.success(request, f"Payroll processed for {created_count} employee(s) in {period.name}.")
    return redirect("payroll:period_detail", pk=period.pk)


@login_required
@permission_required("view_payroll")
def payroll_period_detail(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    payslips = period.payslips.select_related("employee__user", "employee__department").order_by("employee__employee_id")
    return render(request, "payroll/period_detail.html", {"period": period, "payslips": payslips})


@login_required
@permission_required("manage_payroll")
def submit_for_approval(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    if period.status != PayrollStatus.PROCESSED or period.is_locked:
        messages.error(request, "Only processed, unlocked payrolls can be submitted.")
        return redirect("payroll:period_detail", pk=pk)
    if request.method == "POST":
        old = serialize_instance(period)
        period.approval_status = PayrollApprovalStatus.PENDING
        period.submitted_for_approval_at = timezone.now()
        period.save()
        log_change(request, "payroll_submit_approval", instance=period, old_data=old, new_data=serialize_instance(period))
        _notify_payroll_stakeholders(period, "Payroll pending approval", f"{period.name} is awaiting your approval.")
        messages.success(request, "Payroll submitted for approval.")
    return redirect("payroll:period_detail", pk=pk)


@login_required
@permission_required("manage_payroll")
def approve_payroll(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action", "approve")
        old = serialize_instance(period)
        if action == "approve":
            period.approval_status = PayrollApprovalStatus.APPROVED
            period.approved_by = request.user
            period.approved_at = timezone.now()
            period.approval_note = request.POST.get("note", "")
            msg = f"{period.name} has been approved."
        else:
            period.approval_status = PayrollApprovalStatus.REJECTED
            period.approval_note = request.POST.get("note", "Rejected")
            msg = f"{period.name} was rejected."
        period.save()
        log_change(request, f"payroll_{action}", instance=period, old_data=old, new_data=serialize_instance(period))
        messages.success(request, msg)
    return redirect("payroll:period_detail", pk=pk)


@login_required
@permission_required("manage_payroll")
def lock_payroll(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    if period.approval_status != PayrollApprovalStatus.APPROVED:
        messages.error(request, "Payroll must be approved before locking.")
        return redirect("payroll:period_detail", pk=pk)
    if request.method == "POST":
        old = serialize_instance(period)
        period.is_locked = True
        period.locked_by = request.user
        period.locked_at = timezone.now()
        period.save()
        log_change(request, "payroll_lock", instance=period, old_data=old, new_data=serialize_instance(period))
        messages.success(request, f"{period.name} is now locked. No further edits allowed.")
    return redirect("payroll:period_detail", pk=pk)


@login_required
@permission_required("manage_payroll")
def mark_period_paid(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    if not period.is_locked:
        messages.error(request, "Payroll must be locked before marking as paid.")
        return redirect("payroll:period_detail", pk=pk)
    if request.method == "POST":
        old = serialize_instance(period)
        period.status = PayrollStatus.PAID
        period.save()
        log_change(request, "payroll_paid", instance=period, old_data=old, new_data=serialize_instance(period))
        messages.success(request, f"{period.name} marked as paid.")
    return redirect("payroll:period_detail", pk=pk)


@login_required
@permission_required("manage_payroll")
def adjust_payslip(request, pk):
    payslip = get_object_or_404(Payslip, pk=pk)
    if payslip.period.is_locked:
        return JsonResponse({"html": "<p class='text-danger p-3'>This payroll period is locked.</p>"})
    if request.method == "POST":
        old = serialize_instance(payslip)
        form = PayslipAdjustmentForm(request.POST, instance=payslip)
        if form.is_valid():
            payslip = form.save(commit=False)
            payslip.compute()
            log_change(request, "payslip_adjust", instance=payslip, old_data=old, new_data=serialize_instance(payslip))
            messages.success(request, "Payslip adjusted.")
            return redirect("payroll:period_detail", pk=payslip.period_id)
    else:
        form = PayslipAdjustmentForm(instance=payslip)
    html = render_to_string("payroll/_adjust_modal_body.html", {"form": form, "payslip": payslip}, request=request)
    return JsonResponse({"html": html})


@login_required
def my_payslips(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.warning(request, "No employee profile linked to your account yet.")
        return redirect("dashboard:router")
    payslips = employee.payslips.select_related("period").order_by("-period__start_date")
    return render(request, "payroll/my_payslips.html", {"payslips": payslips, "employee": employee})


@login_required
def payslip_detail(request, pk):
    payslip = get_object_or_404(Payslip, pk=pk)
    employee = getattr(request.user, "employee_profile", None)
    if not request.user.is_superuser and payslip.employee != employee:
        from apps.core.permissions import user_has_permission
        if not user_has_permission(request.user, "view_payroll"):
            messages.error(request, "You can only view your own payslips.")
            return redirect("dashboard:router")
    return render(request, "payroll/payslip_detail.html", {"payslip": payslip})


@login_required
def payslip_pdf(request, pk):
    payslip = get_object_or_404(Payslip, pk=pk)
    employee = getattr(request.user, "employee_profile", None)
    if not request.user.is_superuser and payslip.employee != employee:
        from apps.core.permissions import user_has_permission
        if not user_has_permission(request.user, "view_payroll"):
            messages.error(request, "Access denied.")
            return redirect("dashboard:router")
    return payslip_pdf_response(payslip)


@login_required
@permission_required("view_payroll")
def bank_schedule(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    fmt = request.GET.get("format", "csv")
    if fmt not in ("csv", "xlsx"):
        fmt = "csv"
    return bank_schedule_response(period, fmt)
