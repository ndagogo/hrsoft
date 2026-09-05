"""Shared staff-identity conflict detection for invite, direct add, and admit."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .models import Employee, EmployeeInvite, InviteStatus

User = get_user_model()

CONFLICT_MESSAGE = (
    "This staff member already exists (matched by {matched_by}). "
    "Use the existing employee record or Admit from the pending queue if applicable."
)

OPEN_INVITE_STATUSES = (InviteStatus.PENDING, InviteStatus.SUBMITTED)
BLOCKING_INVITE_STATUSES = (InviteStatus.SUBMITTED, InviteStatus.ADMITTED)


@dataclass
class ConflictMatch:
    matched_by: str
    detail: str
    custom_message: str | None = None

    @property
    def message(self) -> str:
        if self.custom_message:
            return self.custom_message
        return CONFLICT_MESSAGE.format(matched_by=self.matched_by)


class StaffConflictError(ValidationError):
    """Raised when creating/admitting would duplicate an existing staff identity."""

    def __init__(self, match: ConflictMatch):
        self.match = match
        super().__init__(match.message)


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def find_staff_conflicts(
    *,
    email: str | None = None,
    username: str | None = None,
    biometric_id: str | None = None,
    exclude_user_id: int | None = None,
    exclude_employee_id: int | None = None,
    exclude_invite_id: int | None = None,
    check_open_invite: bool = True,
    check_blocking_invite: bool = True,
) -> ConflictMatch | None:
    """
    Return the first conflict found, or None.

    Checks (case-insensitive where relevant):
    1. User with same email who already has an employee_profile
    2. User with same username
    3. Employee with same biometric_id (if provided)
    4. Invite already submitted/admitted for same email (optional)
    """
    email_norm = normalize_email(email)
    username_norm = (username or "").strip()
    bio = (biometric_id or "").strip() or None

    if email_norm:
        user_qs = User.objects.filter(email__iexact=email_norm).select_related("employee_profile")
        if exclude_user_id:
            user_qs = user_qs.exclude(pk=exclude_user_id)
        for user in user_qs:
            if hasattr(user, "employee_profile"):
                if exclude_employee_id and user.employee_profile.pk == exclude_employee_id:
                    continue
                return ConflictMatch("email", f"user#{user.pk}")

    if username_norm:
        user_qs = User.objects.filter(username__iexact=username_norm)
        if exclude_user_id:
            user_qs = user_qs.exclude(pk=exclude_user_id)
        if user_qs.exists():
            return ConflictMatch("username", username_norm)

    if bio:
        emp_qs = Employee.objects.filter(biometric_id=bio)
        if exclude_employee_id:
            emp_qs = emp_qs.exclude(pk=exclude_employee_id)
        if emp_qs.exists():
            return ConflictMatch("biometric ID", bio)

    if email_norm and check_blocking_invite:
        invite_qs = EmployeeInvite.objects.filter(
            email__iexact=email_norm,
            status__in=BLOCKING_INVITE_STATUSES,
        )
        if exclude_invite_id:
            invite_qs = invite_qs.exclude(pk=exclude_invite_id)
        if invite_qs.exists():
            return ConflictMatch("email (invite already submitted)", email_norm)

    if email_norm and check_open_invite:
        # Used at invite-send time: block duplicate pending invites
        pending_qs = EmployeeInvite.objects.filter(
            email__iexact=email_norm,
            status=InviteStatus.PENDING,
        )
        if exclude_invite_id:
            pending_qs = pending_qs.exclude(pk=exclude_invite_id)
        if pending_qs.exists():
            return ConflictMatch("email (open invite)", email_norm)

    return None


def assert_no_staff_conflict(**kwargs) -> None:
    match = find_staff_conflicts(**kwargs)
    if match:
        raise StaffConflictError(match)


def cancel_open_invites_for_email(email: str, reason: str = "Cancelled after direct employee create.") -> int:
    """Cancel pending invites for an email so self-onboard cannot create a duplicate."""
    email_norm = normalize_email(email)
    if not email_norm:
        return 0
    updated = EmployeeInvite.objects.filter(
        email__iexact=email_norm,
        status=InviteStatus.PENDING,
    ).update(status=InviteStatus.CANCELLED, conflict_reason=reason[:255])
    return updated
