"""Employee invite lifecycle: create/send, self-onboard, admit, reject."""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.system_settings.services import branding

from .conflicts import (
    ConflictMatch,
    StaffConflictError,
    assert_no_staff_conflict,
    cancel_open_invites_for_email,
    normalize_email,
)
from .models import Employee, EmployeeInvite, EmploymentStatus, EmploymentType, InviteStatus
from .utils import generate_employee_id

User = get_user_model()

INVITE_VALID_DAYS = 7


def _default_expires_at():
    return timezone.now() + timedelta(days=INVITE_VALID_DAYS)


def create_invite(*, email, invited_by, role=None, department=None, designation=None,
                  branches=None, employment_type=None, manager=None) -> EmployeeInvite:
    email_norm = normalize_email(email)
    assert_no_staff_conflict(
        email=email_norm,
        check_open_invite=True,
        check_blocking_invite=True,
    )

    invite = EmployeeInvite(
        email=email_norm,
        token=secrets.token_urlsafe(32),
        status=InviteStatus.PENDING,
        invited_by=invited_by,
        role=role,
        department=department,
        designation=designation,
        employment_type=employment_type or EmploymentType.FULL_TIME,
        manager=manager,
        expires_at=_default_expires_at(),
    )
    invite.save()
    if branches is not None:
        invite.branches.set(branches)
    return invite


def send_invite_email(invite: EmployeeInvite, request=None) -> None:
    company = branding().get("COMPANY_NAME") or getattr(settings, "COMPANY_NAME", "HRMS")
    if request is not None:
        onboard_url = request.build_absolute_uri(invite.get_onboard_url())
    else:
        base = getattr(settings, "SITE_URL", None) or "http://localhost:8000"
        onboard_url = f"{base.rstrip('/')}{invite.get_onboard_url()}"

    subject = f"You're invited to join {company}"
    body = render_to_string(
        "employees/email/invite_staff.txt",
        {
            "company_name": company,
            "onboard_url": onboard_url,
            "expires_at": invite.expires_at,
            "invite": invite,
        },
    )
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@hrms.local"),
        recipient_list=[invite.email],
        fail_silently=False,
    )


@transaction.atomic
def create_and_send_invite(request, *, email, role=None, department=None, designation=None,
                           branches=None, employment_type=None, manager=None) -> EmployeeInvite:
    invite = create_invite(
        email=email,
        invited_by=request.user,
        role=role,
        department=department,
        designation=designation,
        branches=branches,
        employment_type=employment_type,
        manager=manager,
    )
    send_invite_email(invite, request=request)
    return invite


def get_valid_pending_invite(token: str) -> EmployeeInvite | None:
    invite = (
        EmployeeInvite.objects.select_related(
            "role", "department", "designation", "manager", "invited_by"
        )
        .prefetch_related("branches")
        .filter(token=token)
        .first()
    )
    if not invite:
        return None
    if invite.status != InviteStatus.PENDING:
        return invite
    if invite.is_expired:
        invite.status = InviteStatus.EXPIRED
        invite.save(update_fields=["status"])
    return invite


@transaction.atomic
def complete_self_onboard(invite: EmployeeInvite, cleaned_data: dict) -> Employee:
    """
    Create inactive User + pending_admission Employee from invite self-onboard form data.
    """
    if invite.status != InviteStatus.PENDING:
        raise StaffConflictError(ConflictMatch(
            "invite status", invite.status,
            custom_message="This invite is no longer valid.",
        ))

    if invite.is_expired:
        invite.status = InviteStatus.EXPIRED
        invite.save(update_fields=["status"])
        raise StaffConflictError(ConflictMatch(
            "expired invite", invite.token,
            custom_message="This invite has expired. Please ask HR to send a new invitation.",
        ))

    email = normalize_email(invite.email)
    username = (cleaned_data.get("username") or "").strip()
    biometric_id = cleaned_data.get("biometric_id") or None

    try:
        assert_no_staff_conflict(
            email=email,
            username=username,
            biometric_id=biometric_id,
            exclude_invite_id=invite.pk,
            check_open_invite=False,
            check_blocking_invite=True,
        )
    except StaffConflictError as exc:
        invite.status = InviteStatus.CONFLICT
        invite.conflict_reason = str(exc)[:255]
        invite.save(update_fields=["status", "conflict_reason"])
        raise

    user = User(
        username=username,
        email=email,
        first_name=cleaned_data.get("first_name", "").strip(),
        last_name=cleaned_data.get("last_name", "").strip(),
        phone_number=cleaned_data.get("phone_number", "").strip(),
        role=invite.role,
        is_active=False,
        is_active_employee=False,
        must_change_password=False,
    )
    user.set_password(cleaned_data["password1"])
    user.save()

    employee = Employee(
        user=user,
        employee_id=generate_employee_id(),
        department=invite.department,
        designation=invite.designation,
        manager=invite.manager,
        employment_type=invite.employment_type,
        status=EmploymentStatus.PENDING_ADMISSION,
        date_joined=timezone.now().date(),
        gender=cleaned_data.get("gender", ""),
        date_of_birth=cleaned_data.get("date_of_birth"),
        address=cleaned_data.get("address", ""),
        emergency_contact_name=cleaned_data.get("emergency_contact_name", ""),
        emergency_contact_phone=cleaned_data.get("emergency_contact_phone", ""),
        biometric_id=biometric_id,
    )
    employee.save()
    branch_ids = list(invite.branches.values_list("pk", flat=True))
    if branch_ids:
        employee.branches.set(branch_ids)

    payload = {
        k: (str(v) if v is not None and not isinstance(v, (str, int, float, bool, list, dict)) else v)
        for k, v in cleaned_data.items()
        if k not in ("password1", "password2")
    }
    invite.user = user
    invite.employee = employee
    invite.status = InviteStatus.SUBMITTED
    invite.submitted_at = timezone.now()
    invite.submitted_payload = payload
    invite.save()
    return employee


@transaction.atomic
def admit_staff(invite: EmployeeInvite) -> Employee:
    if invite.status == InviteStatus.CONFLICT:
        raise StaffConflictError(ConflictMatch(
            "conflict",
            invite.conflict_reason or "conflict",
            custom_message=invite.conflict_reason
            or "This invite was marked as a conflict and cannot be admitted.",
        ))
    if invite.status != InviteStatus.SUBMITTED or not invite.employee or not invite.user:
        raise StaffConflictError(ConflictMatch(
            "invite status", invite.status,
            custom_message="Invite is not awaiting admission.",
        ))

    employee = invite.employee
    user = invite.user

    assert_no_staff_conflict(
        email=user.email,
        username=user.username,
        biometric_id=employee.biometric_id,
        exclude_user_id=user.pk,
        exclude_employee_id=employee.pk,
        exclude_invite_id=invite.pk,
        check_open_invite=False,
        check_blocking_invite=False,
    )

    user.is_active = True
    user.is_active_employee = True
    user.save(update_fields=["is_active", "is_active_employee"])

    employee.status = EmploymentStatus.ACTIVE
    employee.save(update_fields=["status", "updated_at"])

    invite.status = InviteStatus.ADMITTED
    invite.admitted_at = timezone.now()
    invite.save(update_fields=["status", "admitted_at"])

    cancel_open_invites_for_email(user.email, reason="Cancelled after staff admission.")
    return employee


@transaction.atomic
def reject_staff(invite: EmployeeInvite, reason: str = "") -> None:
    if invite.user_id:
        User.objects.filter(pk=invite.user_id).update(is_active=False, is_active_employee=False)
    if invite.employee_id:
        Employee.objects.filter(pk=invite.employee_id).update(status=EmploymentStatus.TERMINATED)
    invite.status = InviteStatus.CANCELLED
    if reason:
        invite.conflict_reason = reason[:255]
        invite.save(update_fields=["status", "conflict_reason"])
    else:
        invite.save(update_fields=["status"])
