"""Stand-in employee eligibility and coverage workflow."""

from django.db.models import Q
from django.utils import timezone

from apps.employees.models import Employee, EmploymentStatus
from apps.notifications.services import deliver_notification

from .models import LeaveRequest, LeaveStandInRequest, LeaveStandInStatus, LeaveStatus


def get_eligible_stand_in_candidates(requesting_employee, start_date=None, end_date=None, exclude_request=None):
    """Active colleagues in the same department (and branch) eligible to stand in."""
    if not requesting_employee or not requesting_employee.department_id:
        return Employee.objects.none()

    dept = requesting_employee.department
    qs = (
        Employee.objects.filter(
            department_id=dept.pk,
            status=EmploymentStatus.ACTIVE,
            user__is_active=True,
            user__is_active_employee=True,
        )
        .exclude(pk=requesting_employee.pk)
        .select_related("user", "designation", "department")
        .order_by("user__last_name", "user__first_name")
    )

    if dept.branch_id:
        qs = qs.filter(department__branch_id=dept.branch_id)

    if not start_date or not end_date:
        return qs

    eligible_ids = []
    for candidate in qs:
        ok, _msg = validate_stand_in_candidate(
            requesting_employee, candidate, start_date, end_date, exclude_request=exclude_request
        )
        if ok:
            eligible_ids.append(candidate.pk)
    return qs.filter(pk__in=eligible_ids)


def validate_stand_in_candidate(requesting_employee, candidate, start_date, end_date, exclude_request=None):
    if not candidate or candidate.pk == requesting_employee.pk:
        return False, "You cannot nominate yourself as stand-in."
    if candidate.status != EmploymentStatus.ACTIVE:
        return False, f"{candidate.full_name} is not an active employee."
    if not candidate.user.is_active or not candidate.user.is_active_employee:
        return False, f"{candidate.full_name}'s account is inactive."
    if candidate.department_id != requesting_employee.department_id:
        return False, "Stand-in must be in the same department."
    req_branch = requesting_employee.department.branch_id if requesting_employee.department else None
    cand_branch = candidate.department.branch_id if candidate.department else None
    if req_branch and cand_branch and req_branch != cand_branch:
        return False, "Stand-in must be in the same branch."

    on_leave = LeaveRequest.objects.filter(
        employee=candidate,
        status=LeaveStatus.APPROVED,
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if on_leave.exists():
        return False, f"{candidate.full_name} is already on approved leave during these dates."

    covering = LeaveStandInRequest.objects.filter(
        stand_in_employee=candidate,
        status=LeaveStandInStatus.ACCEPTED,
        leave_request__status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED],
        leave_request__start_date__lte=end_date,
        leave_request__end_date__gte=start_date,
    )
    if exclude_request:
        covering = covering.exclude(leave_request=exclude_request)
    if covering.exists():
        return False, f"{candidate.full_name} is already covering another colleague for overlapping dates."

    return True, ""


def create_stand_in_request(leave_request: LeaveRequest, stand_in_employee: Employee):
    leave_request.stand_in_requests.filter(status=LeaveStandInStatus.PENDING).update(
        status=LeaveStandInStatus.CANCELLED,
    )
    leave_request.stand_in_employee = stand_in_employee
    leave_request.status = LeaveStatus.AWAITING_STANDIN
    leave_request.current_stage = ""
    leave_request.save(update_fields=["stand_in_employee", "status", "current_stage", "updated_at"])

    req = LeaveStandInRequest.objects.create(
        leave_request=leave_request,
        employee=leave_request.employee,
        stand_in_employee=stand_in_employee,
        status=LeaveStandInStatus.PENDING,
    )
    _notify_stand_in(req)
    return req


def accept_stand_in(stand_in_request: LeaveStandInRequest, user, remarks=""):
    if stand_in_request.status != LeaveStandInStatus.PENDING:
        raise ValueError("This stand-in request is no longer pending.")
    profile = getattr(user, "employee_profile", None)
    if not profile or profile.pk != stand_in_request.stand_in_employee_id:
        raise PermissionError("Only the nominated stand-in can accept this request.")

    stand_in_request.status = LeaveStandInStatus.ACCEPTED
    stand_in_request.remarks = remarks or ""
    stand_in_request.responded_at = timezone.now()
    stand_in_request.save()

    leave_request = stand_in_request.leave_request
    leave_request.status = LeaveStatus.PENDING
    leave_request.save(update_fields=["status", "updated_at"])

    from . import workflow
    workflow.initialize_approval_chain(leave_request)

    _notify_employee(
        leave_request,
        "Stand-in accepted",
        f"{stand_in_request.stand_in_employee.full_name} accepted your stand-in request. "
        "Your leave is now with your Head of Department for approval.",
    )
    return stand_in_request


def decline_stand_in(stand_in_request: LeaveStandInRequest, user, remarks=""):
    if stand_in_request.status != LeaveStandInStatus.PENDING:
        raise ValueError("This stand-in request is no longer pending.")
    profile = getattr(user, "employee_profile", None)
    if not profile or profile.pk != stand_in_request.stand_in_employee_id:
        raise PermissionError("Only the nominated stand-in can decline this request.")

    stand_in_request.status = LeaveStandInStatus.DECLINED
    stand_in_request.remarks = remarks or ""
    stand_in_request.responded_at = timezone.now()
    stand_in_request.save()

    leave_request = stand_in_request.leave_request
    leave_request.status = LeaveStatus.AWAITING_STANDIN
    leave_request.current_stage = ""
    leave_request.approval_steps.all().delete()
    leave_request.save(update_fields=["status", "current_stage", "updated_at"])

    _notify_employee(
        leave_request,
        "Stand-in declined",
        f"{stand_in_request.stand_in_employee.full_name} declined your stand-in request. "
        "Please select another colleague to continue.",
    )
    return stand_in_request


def pending_stand_in_for(employee):
    return (
        LeaveStandInRequest.objects.filter(
            stand_in_employee=employee,
            status=LeaveStandInStatus.PENDING,
        )
        .select_related(
            "leave_request__leave_type",
            "leave_request__employee__user",
            "leave_request__employee__department",
            "employee__user",
        )
        .order_by("created_at")
    )


def stand_in_history_for(employee):
    return (
        LeaveStandInRequest.objects.filter(stand_in_employee=employee)
        .exclude(status=LeaveStandInStatus.PENDING)
        .select_related("leave_request__leave_type", "employee__user")
        .order_by("-responded_at", "-created_at")[:30]
    )


def _notify_stand_in(stand_in_request: LeaveStandInRequest):
    user = stand_in_request.stand_in_employee.user
    lr = stand_in_request.leave_request
    emp = stand_in_request.employee
    deliver_notification(
        user,
        f"Stand-in request from {emp.full_name}",
        (
            f"{emp.full_name} nominated you to stand in during "
            f"{lr.leave_type.name} ({lr.start_date} – {lr.end_date}). "
            "Please accept or decline."
        ),
        category="leave",
        link="/leave/stand-in/",
        channels=["email"] if user.email else [],
    )


def _notify_employee(leave_request: LeaveRequest, title: str, message: str):
    user = leave_request.employee.user
    if not user:
        return
    deliver_notification(
        user,
        title,
        message,
        category="leave",
        link=f"/leave/my-requests/{leave_request.pk}/",
        channels=["email"] if user.email else [],
    )
