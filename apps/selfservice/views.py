from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from apps.attendance.models import AttendanceRecord, AttendanceStatus
from apps.core.audit import log_change, serialize_instance
from apps.core.permissions import permission_required
from apps.notifications.services import deliver_notification
from .models import ProfileUpdateRequest, AttendanceCorrectionRequest, LoanRequest, TrainingRequest, RequestStatus
from .forms import ProfileUpdateForm, AttendanceCorrectionForm, LoanRequestForm, TrainingRequestForm


def _apply_approved_request(obj, model_key):
    """Apply approved self-service changes to the underlying employee/user records."""
    if model_key == "profile" and isinstance(obj, ProfileUpdateRequest):
        employee = obj.employee
        field = obj.field_name
        value = obj.requested_value
        if field == "phone_number":
            user = employee.user
            old = serialize_instance(user, fields=["phone_number"])
            user.phone_number = value
            user.save(update_fields=["phone_number"])
            log_change(None, "selfservice_profile_apply", instance=user, old_data=old, new_data=serialize_instance(user, fields=["phone_number"]))
        elif hasattr(employee, field):
            old = serialize_instance(employee, fields=[field])
            setattr(employee, field, value)
            employee.save(update_fields=[field])
            log_change(None, "selfservice_profile_apply", instance=employee, old_data=old, new_data=serialize_instance(employee, fields=[field]))
    elif model_key == "attendance" and isinstance(obj, AttendanceCorrectionRequest):
        employee = obj.employee
        record, _ = AttendanceRecord.objects.get_or_create(employee=employee, date=obj.date, defaults={"status": AttendanceStatus.PRESENT})
        old = serialize_instance(record)
        if obj.requested_check_in:
            record.check_in = timezone.make_aware(datetime.combine(obj.date, obj.requested_check_in))
        if obj.requested_check_out:
            record.check_out = timezone.make_aware(datetime.combine(obj.date, obj.requested_check_out))
        record.status = AttendanceStatus.PRESENT
        record.is_manual_override = True
        record.notes = (record.notes + " " if record.notes else "") + f"Self-service correction approved: {obj.reason[:120]}"
        record.save()
        log_change(None, "selfservice_attendance_apply", instance=record, old_data=old, new_data=serialize_instance(record))


@login_required
def selfservice_hub(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.warning(request, "No employee profile linked to your account.")
        return redirect("dashboard:router")
    return render(request, "selfservice/hub.html", {
        "employee": employee,
        "profile_requests": employee.profile_update_requests.all()[:10],
        "attendance_requests": employee.attendance_corrections.all()[:10],
        "loan_requests": employee.loan_requests.all()[:10],
        "training_requests": employee.training_requests.all()[:10],
    })


@login_required
def profile_update_create(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        return redirect("dashboard:router")
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.employee = employee
            req.save()
            deliver_notification(
                request.user, "Profile update submitted",
                "Your profile change request is pending HR review.",
                category="approval", link="/selfservice/",
            )
            messages.success(request, "Profile update request submitted.")
            return redirect("selfservice:hub")
    else:
        form = ProfileUpdateForm()
    return render(request, "selfservice/profile_request.html", {"form": form})


@login_required
def attendance_correction_create(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        return redirect("dashboard:router")
    if request.method == "POST":
        form = AttendanceCorrectionForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.employee = employee
            req.save()
            messages.success(request, "Attendance correction request submitted.")
            return redirect("selfservice:hub")
    else:
        form = AttendanceCorrectionForm()
    return render(request, "selfservice/attendance_request.html", {"form": form})


@login_required
def loan_request_create(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        return redirect("dashboard:router")
    if request.method == "POST":
        form = LoanRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.employee = employee
            req.save()
            messages.success(request, "Loan request submitted.")
            return redirect("selfservice:hub")
    else:
        form = LoanRequestForm()
    return render(request, "selfservice/loan_request.html", {"form": form})


@login_required
def training_request_create(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        return redirect("dashboard:router")
    if request.method == "POST":
        form = TrainingRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.employee = employee
            req.save()
            messages.success(request, "Training request submitted.")
            return redirect("selfservice:hub")
    else:
        form = TrainingRequestForm()
    return render(request, "selfservice/training_request.html", {"form": form})


@login_required
@permission_required("manage_employees")
def approvals_list(request):
    return render(request, "selfservice/approvals.html", {
        "profile_requests": ProfileUpdateRequest.objects.filter(status=RequestStatus.PENDING).select_related("employee__user")[:20],
        "attendance_requests": AttendanceCorrectionRequest.objects.filter(status=RequestStatus.PENDING).select_related("employee__user")[:20],
        "loan_requests": LoanRequest.objects.filter(status=RequestStatus.PENDING).select_related("employee__user")[:20],
        "training_requests": TrainingRequest.objects.filter(status=RequestStatus.PENDING).select_related("employee__user")[:20],
    })


@login_required
@permission_required("manage_employees")
def approve_request(request, model, pk, action):
    models_map = {
        "profile": ProfileUpdateRequest,
        "attendance": AttendanceCorrectionRequest,
        "loan": LoanRequest,
        "training": TrainingRequest,
    }
    Model = models_map.get(model)
    if not Model:
        messages.error(request, "Invalid request type.")
        return redirect("selfservice:approvals")
    obj = get_object_or_404(Model, pk=pk)
    if request.method == "POST":
        note = request.POST.get("review_note", "")
        old = serialize_instance(obj)
        obj.status = RequestStatus.APPROVED if action == "approve" else RequestStatus.REJECTED
        obj.reviewed_by = request.user
        obj.review_note = note
        obj.reviewed_at = timezone.now()
        obj.save()
        if action == "approve":
            _apply_approved_request(obj, model)
        log_change(request, f"selfservice_{action}", instance=obj, old_data=old, new_data=serialize_instance(obj))
        deliver_notification(
            obj.employee.user,
            f"Request {obj.get_status_display().lower()}",
            f"Your {model} request was {obj.get_status_display().lower()}. {note}",
            category="approval",
            channels=["email"],
        )
        messages.success(request, f"Request {obj.get_status_display().lower()}.")
    return redirect("selfservice:approvals")
