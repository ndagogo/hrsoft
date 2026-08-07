"""Asset management workflows — assignment, returns, maintenance, requests."""

from django.db import transaction
from django.utils import timezone

from apps.notifications.services import deliver_notification

from .models import (
    Asset,
    AssetAssignment,
    AssetDisposal,
    AssetHistory,
    AssetHistoryEvent,
    AssetMaintenance,
    AssetRequest,
    AssetRequestStatus,
    AssetStatus,
    AssetTransfer,
    MaintenanceStatus,
)


def log_history(asset, event_type, summary, *, actor=None, employee=None, detail="", metadata=None):
    return AssetHistory.objects.create(
        asset=asset,
        event_type=event_type,
        summary=summary,
        detail=detail,
        actor=actor,
        employee=employee,
        metadata=metadata or {},
    )


def register_asset(asset, user):
    log_history(
        asset, AssetHistoryEvent.REGISTERED,
        f"Asset registered: {asset.name}",
        actor=user,
    )


@transaction.atomic
def approve_asset(asset, user):
    if asset.status != AssetStatus.PENDING_APPROVAL:
        return False
    asset.status = AssetStatus.AVAILABLE
    asset.approved_by = user
    asset.approved_at = timezone.now()
    asset.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    log_history(asset, AssetHistoryEvent.APPROVED, "Asset approved for use", actor=user)
    return True


@transaction.atomic
def assign_asset(asset, employee, *, user, condition, accessories="", expected_return=None, notes=""):
    if asset.status not in (AssetStatus.AVAILABLE, AssetStatus.RESERVED):
        raise ValueError("Asset is not available for assignment.")
    assignment = AssetAssignment.objects.create(
        asset=asset,
        employee=employee,
        department=employee.department,
        assigned_date=timezone.now().date(),
        expected_return_date=expected_return,
        condition_on_assign=condition,
        accessories_issued=accessories,
        notes=notes,
        assigned_by=user,
        approved_by=user,
    )
    asset.status = AssetStatus.ASSIGNED
    asset.save(update_fields=["status", "updated_at"])
    log_history(
        asset, AssetHistoryEvent.ASSIGNED,
        f"Assigned to {employee.full_name}",
        actor=user, employee=employee,
        detail=accessories,
    )
    deliver_notification(
        employee.user,
        f"Asset issued: {asset.name}",
        f"You have been assigned {asset.asset_number} — {asset.name}.",
        category="general",
        link=f"/assets/my/",
    )
    return assignment


@transaction.atomic
def return_asset(assignment, *, user, condition_on_return, inspection_notes="", accessories_returned=True):
    if not assignment.is_active:
        raise ValueError("Assignment is already closed.")
    assignment.is_active = False
    assignment.returned_date = timezone.now().date()
    assignment.condition_on_return = condition_on_return
    assignment.inspection_notes = inspection_notes
    assignment.inspected_by = user
    assignment.save()
    asset = assignment.asset
    asset.condition = condition_on_return
    asset.status = AssetStatus.AVAILABLE
    asset.save(update_fields=["condition", "status", "updated_at"])
    log_history(
        asset, AssetHistoryEvent.RETURNED,
        f"Returned by {assignment.employee.full_name}",
        actor=user, employee=assignment.employee,
        detail=inspection_notes,
        metadata={"accessories_returned": accessories_returned},
    )
    log_history(asset, AssetHistoryEvent.INSPECTED, "Post-return inspection completed", actor=user)
    return assignment


@transaction.atomic
def transfer_asset(assignment, *, user, to_employee=None, to_department=None, notes=""):
    asset = assignment.asset
    from_emp = assignment.employee
    from_dept = assignment.department
    AssetTransfer.objects.create(
        asset=asset,
        from_employee=from_emp,
        to_employee=to_employee,
        from_department=from_dept,
        to_department=to_department or (to_employee.department if to_employee else None),
        transferred_by=user,
        notes=notes,
    )
    if to_employee and to_employee != from_emp:
        assignment.is_active = False
        assignment.returned_date = timezone.now().date()
        assignment.save()
        assign_asset(
            asset, to_employee, user=user,
            condition=assignment.condition_on_assign,
            accessories=assignment.accessories_issued,
            notes=f"Transferred from {from_emp.full_name}. {notes}",
        )
    elif to_department:
        assignment.department = to_department
        assignment.save(update_fields=["department"])
        asset.department = to_department
        asset.save(update_fields=["department", "updated_at"])
    log_history(
        asset, AssetHistoryEvent.TRANSFERRED,
        f"Transfer: {from_emp.full_name} → {to_employee.full_name if to_employee else to_department}",
        actor=user, employee=to_employee or from_emp, detail=notes,
    )


@transaction.atomic
def open_maintenance(asset, *, user, problem, technician="", vendor=""):
    if asset.status == AssetStatus.ASSIGNED:
        pass
    record = AssetMaintenance.objects.create(
        asset=asset, reported_by=user, problem=problem,
        technician=technician, vendor=vendor,
    )
    asset.status = AssetStatus.MAINTENANCE
    asset.save(update_fields=["status", "updated_at"])
    log_history(asset, AssetHistoryEvent.MAINTENANCE_OPENED, problem[:200], actor=user)
    return record


@transaction.atomic
def complete_maintenance(record, *, user, repair_cost=0, notes="", next_date=None):
    record.status = MaintenanceStatus.COMPLETED
    record.repair_cost = repair_cost
    record.notes = notes
    record.completed_at = timezone.now()
    record.next_maintenance_date = next_date
    record.save()
    asset = record.asset
    asset.next_maintenance_date = next_date
    has_active = asset.assignments.filter(is_active=True).exists()
    asset.status = AssetStatus.ASSIGNED if has_active else AssetStatus.AVAILABLE
    asset.save(update_fields=["status", "next_maintenance_date", "updated_at"])
    log_history(asset, AssetHistoryEvent.MAINTENANCE_COMPLETED, "Maintenance completed", actor=user, detail=notes)
    return record


@transaction.atomic
def dispose_asset(asset, *, user, reason, method="", salvage_value=0):
    AssetDisposal.objects.create(
        asset=asset, disposed_at=timezone.now().date(),
        reason=reason, method=method, salvage_value=salvage_value, disposed_by=user,
    )
    asset.assignments.filter(is_active=True).update(
        is_active=False, returned_date=timezone.now().date(),
    )
    asset.status = AssetStatus.DISPOSED
    asset.is_active = False
    asset.save(update_fields=["status", "is_active", "updated_at"])
    log_history(asset, AssetHistoryEvent.DISPOSED, reason[:200], actor=user)


def employee_active_assignments(employee):
    return AssetAssignment.objects.filter(employee=employee, is_active=True).select_related("asset", "asset__category")


def employee_offboarding_ready(employee):
    return not employee_active_assignments(employee).exists()


def advance_asset_request(req, *, user, stage):
    """stage: supervisor | it | store | issue | reject"""
    if stage == "supervisor" and req.status == AssetRequestStatus.PENDING:
        req.status = AssetRequestStatus.SUPERVISOR_APPROVED
        req.supervisor_approved_by = user
    elif stage == "it" and req.status == AssetRequestStatus.SUPERVISOR_APPROVED:
        req.status = AssetRequestStatus.IT_APPROVED
        req.it_approved_by = user
    elif stage == "store" and req.status == AssetRequestStatus.IT_APPROVED:
        req.status = AssetRequestStatus.STORE_APPROVED
        req.store_approved_by = user
    elif stage == "reject":
        req.status = AssetRequestStatus.REJECTED
        req.rejection_note = req.rejection_note or "Rejected"
    else:
        return False
    req.save()
    return True


@transaction.atomic
def issue_from_request(req, asset, user):
    if req.status != AssetRequestStatus.STORE_APPROVED:
        raise ValueError("Request must be store-approved before issuing.")
    assign_asset(asset, req.employee, user=user, condition=asset.condition, notes=req.justification)
    req.status = AssetRequestStatus.ISSUED
    req.issued_asset = asset
    req.save()
    return req


def dashboard_metrics():
    qs = Asset.objects.filter(is_active=True)
    return {
        "total": qs.count(),
        "available": qs.filter(status=AssetStatus.AVAILABLE).count(),
        "assigned": qs.filter(status=AssetStatus.ASSIGNED).count(),
        "maintenance": qs.filter(status=AssetStatus.MAINTENANCE).count(),
        "lost": qs.filter(status=AssetStatus.LOST).count(),
        "damaged": qs.filter(status=AssetStatus.DAMAGED).count(),
        "retired": qs.filter(status=AssetStatus.RETIRED).count(),
        "pending_approval": qs.filter(status=AssetStatus.PENDING_APPROVAL).count(),
    }


def send_asset_reminders():
    """Called by management command or cron — warranty, maintenance, overdue returns."""
    today = timezone.now().date()
    soon = today + timezone.timedelta(days=30)
    for asset in Asset.objects.filter(is_active=True, warranty_end__lte=soon, warranty_end__gte=today):
        if asset.assigned_employee:
            deliver_notification(
                asset.assigned_employee.user,
                f"Warranty expiring: {asset.name}",
                f"Warranty for {asset.asset_number} ends {asset.warranty_end}.",
                category="general",
            )
    for a in AssetAssignment.objects.filter(is_active=True, expected_return_date__lt=today):
        deliver_notification(
            a.employee.user,
            f"Asset overdue for return: {a.asset.name}",
            f"Please return {a.asset.asset_number} — expected {a.expected_return_date}.",
            category="general",
        )
