"""Multi-stage leave approval: Employee → HOD → HR → General Manager."""

from django.db.models import Q
from django.utils import timezone

from apps.core.permissions import user_has_permission
from apps.notifications.services import deliver_notification

from .models import (
    APPROVAL_CHAIN,
    LeaveApprovalStage,
    LeaveApprovalStep,
    LeaveRequest,
    LeaveStatus,
    LeaveStepStatus,
)

HR_ROLES = {"Admin", "HR Manager", "HR Officer"}
GM_ROLES = {"Admin", "General Manager"}


def _role_name(user):
    role = getattr(user, "role", None)
    return role.name if role else ""


def is_department_head_for(user, employee):
    """True if user is the HOD/manager for this employee's department."""
    profile = getattr(user, "employee_profile", None)
    if not profile or not employee:
        return False
    if employee.manager_id and employee.manager_id == profile.pk:
        return True
    dept = employee.department
    if dept and dept.head_id and dept.head_id == profile.pk:
        return True
    return False


def can_act_as_hod(user):
    return user_has_permission(user, "approve_leave") and bool(getattr(user, "employee_profile", None))


def can_act_as_hr(user):
    if not user_has_permission(user, "approve_leave"):
        return False
    if user.is_superuser:
        return True
    if user_has_permission(user, "approve_leave_hr"):
        return True
    return _role_name(user) in HR_ROLES


def can_act_as_gm(user):
    if not user_has_permission(user, "approve_leave"):
        return False
    if user.is_superuser:
        return True
    if user_has_permission(user, "approve_leave_gm"):
        return True
    return _role_name(user) in GM_ROLES


def user_can_review_request(user, leave_request: LeaveRequest) -> bool:
    if leave_request.status != LeaveStatus.PENDING:
        return False
    if not leave_request.stand_in_accepted:
        return False
    stage = leave_request.current_stage
    if user.is_superuser or _role_name(user) == "Admin":
        return True
    if stage == LeaveApprovalStage.HOD:
        return can_act_as_hod(user) and is_department_head_for(user, leave_request.employee)
    if stage == LeaveApprovalStage.HR:
        return can_act_as_hr(user)
    if stage == LeaveApprovalStage.GM:
        return can_act_as_gm(user)
    return False


def pending_for_user(user):
    """Leave requests the current user may action right now (scoped)."""
    qs = (
        LeaveRequest.objects.filter(status=LeaveStatus.PENDING)
        .select_related("employee__user", "employee__department", "leave_type")
        .prefetch_related("approval_steps")
        .order_by("created_at")
    )
    if user.is_superuser or _role_name(user) == "Admin":
        # Admin sees queue items they can action at each stage; still respect stage rules for HOD scope
        pass

    ids = []
    for lr in qs:
        if lr.stand_in_accepted and user_can_review_request(user, lr):
            ids.append(lr.pk)
    return LeaveRequest.objects.filter(pk__in=ids).select_related(
        "employee__user", "employee__department", "leave_type"
    ).prefetch_related("approval_steps").order_by("created_at")


def visible_history_for_user(user, limit=20):
    """Decided requests visible to this approver (own dept for HOD; HR/GM/Admin broader)."""
    base = (
        LeaveRequest.objects.exclude(status=LeaveStatus.PENDING)
        .select_related("employee__user", "employee__department", "leave_type", "reviewed_by")
        .order_by("-reviewed_at", "-updated_at")
    )
    if user.is_superuser or can_act_as_hr(user) or can_act_as_gm(user):
        return base[:limit]

    profile = getattr(user, "employee_profile", None)
    if not profile:
        return base.none()
    return base.filter(
        Q(employee__manager=profile) | Q(employee__department__head=profile)
    )[:limit]


def initialize_approval_chain(leave_request: LeaveRequest, notify: bool = True):
    """Create HOD → HR → GM steps; activate HOD."""
    leave_request.approval_steps.all().delete()
    for seq, stage in enumerate(APPROVAL_CHAIN, start=1):
        LeaveApprovalStep.objects.create(
            leave_request=leave_request,
            stage=stage,
            sequence=seq,
            status=LeaveStepStatus.PENDING if seq == 1 else LeaveStepStatus.WAITING,
        )
    leave_request.current_stage = APPROVAL_CHAIN[0]
    leave_request.status = LeaveStatus.PENDING
    leave_request.save(update_fields=["current_stage", "status", "updated_at"])
    if notify:
        _notify_stage_actors(leave_request)


def _hod_users_for(employee):
    users = []
    if employee.manager_id and employee.manager.user_id:
        users.append(employee.manager.user)
    dept = employee.department
    if dept and dept.head_id and dept.head.user_id:
        if not any(u.pk == dept.head.user_id for u in users):
            users.append(dept.head.user)
    return users


def _users_with_roles(role_names):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return list(User.objects.filter(role__name__in=role_names, is_active=True))


def _notify_stage_actors(leave_request: LeaveRequest):
    stage = leave_request.current_stage
    emp = leave_request.employee
    title = f"Leave awaiting {dict(LeaveApprovalStage.choices).get(stage, stage)}"
    message = (
        f"{emp.full_name} requested {leave_request.leave_type.name} "
        f"({leave_request.start_date} – {leave_request.end_date})."
    )
    link = "/leave/approvals/"
    recipients = []
    if stage == LeaveApprovalStage.HOD:
        recipients = _hod_users_for(emp)
    elif stage == LeaveApprovalStage.HR:
        recipients = _users_with_roles(list(HR_ROLES))
    elif stage == LeaveApprovalStage.GM:
        recipients = _users_with_roles(list(GM_ROLES))

    for user in recipients:
        if not user or user.pk == emp.user_id:
            continue
        deliver_notification(user, title, message, category="leave", link=link, channels=["email"] if user.email else [])


def _notify_employee(leave_request: LeaveRequest, title: str, message: str):
    user = leave_request.employee.user
    if not user:
        return
    deliver_notification(
        user,
        title,
        message,
        category="leave",
        link="/leave/my-requests/",
        channels=["email"] if user.email else [],
    )


def process_decision(leave_request: LeaveRequest, user, decision: str, note: str = "") -> str:
    """
    Apply approve/reject at the current stage.
    Returns a human-readable result message.
    """
    if not user_can_review_request(user, leave_request):
        raise PermissionError("You are not allowed to review this leave request at the current stage.")

    step = leave_request.approval_steps.filter(
        stage=leave_request.current_stage,
        status=LeaveStepStatus.PENDING,
    ).first()
    if not step:
        raise ValueError("No pending approval step found for this request.")

    if decision == LeaveStatus.REJECTED:
        step.reject(user, note)
        leave_request.status = LeaveStatus.REJECTED
        leave_request.reviewed_by = user
        leave_request.review_note = note or f"Rejected at {step.get_stage_display()}"
        leave_request.reviewed_at = timezone.now()
        leave_request.current_stage = ""
        leave_request.save()
        # Mark remaining waiting steps skipped
        leave_request.approval_steps.filter(status=LeaveStepStatus.WAITING).update(status=LeaveStepStatus.SKIPPED)
        _notify_employee(
            leave_request,
            "Leave request declined",
            f"Your {leave_request.leave_type.name} request was declined at {step.get_stage_display()}. {note}".strip(),
        )
        return f"Leave request rejected at {step.get_stage_display()}."

    # Approve current stage
    step.approve(user, note)
    chain = list(APPROVAL_CHAIN)
    idx = chain.index(leave_request.current_stage)

    if idx >= len(chain) - 1:
        # Final GM approval
        leave_request.status = LeaveStatus.APPROVED
        leave_request.reviewed_by = user
        leave_request.review_note = note or "Fully approved"
        leave_request.reviewed_at = timezone.now()
        leave_request.current_stage = ""
        leave_request.save()
        employee = leave_request.employee
        employee.leave_balance_days = max(0, employee.leave_balance_days - leave_request.days_requested)
        employee.save(update_fields=["leave_balance_days"])
        from .approval_letter import ensure_approval_document
        doc = ensure_approval_document(leave_request)
        _notify_employee(
            leave_request,
            "Leave request approved",
            (
                f"Your {leave_request.leave_type.name} request "
                f"({leave_request.start_date} – {leave_request.end_date}) is fully approved. "
                f"Download your approval letter (Ref: {doc.reference_number})."
            ),
        )
        if leave_request.stand_in_employee and leave_request.stand_in_employee.user:
            deliver_notification(
                leave_request.stand_in_employee.user,
                f"Coverage period starting soon — {employee.full_name}",
                (
                    f"You are the stand-in for {employee.full_name}'s {leave_request.leave_type.name} "
                    f"from {leave_request.start_date} to {leave_request.end_date}."
                ),
                category="leave",
                link=f"/leave/my-requests/{leave_request.pk}/",
            )
        return "Leave request fully approved."

    # Advance to next stage
    next_stage = chain[idx + 1]
    leave_request.current_stage = next_stage
    leave_request.save(update_fields=["current_stage", "updated_at"])
    next_step = leave_request.approval_steps.get(stage=next_stage)
    next_step.mark_pending()
    _notify_stage_actors(leave_request)
    _notify_employee(
        leave_request,
        "Leave request progressed",
        f"Your leave was approved by {step.get_stage_display()} and is now awaiting {dict(LeaveApprovalStage.choices)[next_stage]}.",
    )
    return f"Approved at {step.get_stage_display()}. Now awaiting {dict(LeaveApprovalStage.choices)[next_stage]}."
