"""
Biometric device sync orchestration.

Bridges HRMS employees / attendance with physical terminals:
  - Pull staff IDs from device
  - Push staff IDs to device
  - Pull attendance punches (clock-in / clock-out)
  - Queue commands for remote devices that poll the Device Hub
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.employees.models import Employee

from .models import (
    BiometricDevice,
    DeviceCommand,
    DeviceCommandStatus,
    DeviceCommandType,
    DeviceStaffSnapshot,
    RawPunchLog,
)

logger = logging.getLogger("apps.attendance.biometrics")


def _staff_payload_from_employees(employees=None):
    qs = employees or Employee.objects.filter(status="active").exclude(biometric_id="")
    rows = []
    for emp in qs.select_related("user"):
        rows.append(
            {
                "staff_id": str(emp.biometric_id).strip(),
                "employee_id": emp.employee_id,
                "name": (emp.user.get_full_name() or emp.user.username)[:24],
                "privilege": 0,
                "card": "",
            }
        )
    return rows


def save_staff_snapshots(device, users: list[dict]) -> int:
    """Upsert DeviceStaffSnapshot rows and link to HRMS employees when possible."""
    now = timezone.now()
    count = 0
    for item in users:
        staff_id = str(item.get("staff_id") or item.get("user_id") or "").strip()
        if not staff_id:
            continue
        employee = Employee.objects.filter(biometric_id=staff_id).first()
        DeviceStaffSnapshot.objects.update_or_create(
            device=device,
            staff_id=staff_id,
            defaults={
                "name": (item.get("name") or "")[:120],
                "card_no": str(item.get("card") or item.get("card_no") or "")[:40],
                "privilege": str(item.get("privilege") or "")[:20],
                "raw": item.get("raw") or item,
                "linked_employee": employee,
                "last_seen_at": now,
            },
        )
        count += 1
    return count


def _mark_device_error(device: BiometricDevice, message: str):
    device.last_sync_status = "error"
    device.last_sync_message = message[:255]
    device.last_sync_at = timezone.now()
    device.save(update_fields=["last_sync_status", "last_sync_message", "last_sync_at"])


def pull_staff_from_device(device: BiometricDevice) -> dict:
    """
    Read enrolled staff IDs from the physical device (LAN).
    Currently implemented for ZKTeco via pyzk.
    """
    if device.brand == "zkteco":
        if not device.ip_address:
            return {"ok": False, "detail": "Device IP is required for ZKTeco LAN pull."}
        from .zkteco import DeviceUnreachableError, pull_zk_users

        try:
            users, info = pull_zk_users(device)
        except DeviceUnreachableError as exc:
            logger.warning("pull_staff failed for %s: %s", device, exc)
            _mark_device_error(device, str(exc))
            return {"ok": False, "action": "pull_staff", "detail": str(exc), "message": str(exc)}
        except Exception as exc:
            logger.exception("pull_staff unexpected error for %s", device)
            msg = f"Pull staff failed: {exc}"[:255]
            _mark_device_error(device, msg)
            return {"ok": False, "action": "pull_staff", "detail": msg, "message": msg}

        saved = save_staff_snapshots(device, users)
        device.last_sync_status = "ok"
        device.last_sync_message = info[:255]
        device.last_sync_at = timezone.now()
        device.last_seen_at = timezone.now()
        device.save(update_fields=["last_sync_status", "last_sync_message", "last_sync_at", "last_seen_at"])
        return {
            "ok": True,
            "action": "pull_staff",
            "count": saved,
            "staff": [
                {
                    "staff_id": u["staff_id"],
                    "name": u.get("name", ""),
                    "linked": bool(Employee.objects.filter(biometric_id=u["staff_id"]).exists()),
                }
                for u in users
            ],
            "message": info,
        }

    return {
        "ok": False,
        "detail": (
            f"Direct LAN pull_staff is not implemented for brand '{device.brand}'. "
            "Queue a pull_staff command for a remote bridge, or use Device Hub staff upload."
        ),
    }


def push_staff_to_device(device: BiometricDevice, employees=None) -> dict:
    """Push HRMS employees (with biometric_id) onto the physical device."""
    users = _staff_payload_from_employees(employees)
    if not users:
        return {"ok": False, "detail": "No active employees with biometric IDs to push."}

    if device.brand == "zkteco":
        if not device.ip_address:
            return {"ok": False, "detail": "Device IP is required for ZKTeco LAN push."}
        from .zkteco import DeviceUnreachableError, push_zk_users

        try:
            ok, errors, info = push_zk_users(device, users)
        except DeviceUnreachableError as exc:
            logger.warning("push_staff failed for %s: %s", device, exc)
            _mark_device_error(device, str(exc))
            return {"ok": False, "action": "push_staff", "detail": str(exc), "message": str(exc)}
        except Exception as exc:
            logger.exception("push_staff unexpected error for %s", device)
            msg = f"Push staff failed: {exc}"[:255]
            _mark_device_error(device, msg)
            return {"ok": False, "action": "push_staff", "detail": msg, "message": msg}

        device.last_sync_status = "ok" if errors == 0 else "error"
        device.last_sync_message = info[:255]
        device.last_sync_at = timezone.now()
        device.last_seen_at = timezone.now()
        device.save(update_fields=["last_sync_status", "last_sync_message", "last_sync_at", "last_seen_at"])
        return {
            "ok": errors == 0,
            "action": "push_staff",
            "pushed": ok,
            "failed": errors,
            "total": len(users),
            "message": info,
        }

    return {
        "ok": False,
        "detail": (
            f"Direct LAN push_staff is not implemented for brand '{device.brand}'. "
            "Queue a push_staff command so a remote bridge can download the staff list."
        ),
        "staff_ready": len(users),
    }


def pull_attendance_from_device(device: BiometricDevice, since=None) -> dict:
    """Pull punches from the device and ingest clock-in / clock-out events."""
    from .biometrics import pull_device_events

    if since is None and device.last_sync_at:
        since = device.last_sync_at - timedelta(minutes=5)

    # pull_device_events already updates device sync fields
    before = RawPunchLog.objects.filter(device=device).count()
    count = pull_device_events(device, since=since)
    after = RawPunchLog.objects.filter(device=device).count()
    device.refresh_from_db()

    recent = list(
        RawPunchLog.objects.filter(device=device)
        .select_related("employee")
        .order_by("-timestamp")[:20]
    )
    return {
        "ok": device.last_sync_status != "error",
        "action": "pull_attendance",
        "ingested": count,
        "punch_total_on_device_log": after,
        "new_rows_estimate": max(0, after - before),
        "message": device.last_sync_message,
        "recent_punches": [
            {
                "punch_id": p.pk,
                "staff_id": p.device_employee_no,
                "direction": p.direction,
                "timestamp": p.timestamp.isoformat(),
                "matched": p.matched,
                "employee_id": p.employee.employee_id if p.employee_id else None,
            }
            for p in recent
        ],
    }


def queue_command(device, command: str, *, payload=None, user=None) -> DeviceCommand:
    return DeviceCommand.objects.create(
        device=device,
        command=command,
        payload=payload or {},
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def execute_or_queue(device, command: str, *, user=None, force_queue=False) -> dict:
    """
    Run a sync action immediately for LAN devices, otherwise queue it for the
    remote device/bridge to pick up from the Device Hub.
    """
    can_direct = (
        not force_queue
        and device.brand == "zkteco"
        and bool(device.ip_address)
        and device.connection_mode in ("pull", "both")
    )

    if can_direct:
        if command == DeviceCommandType.PULL_STAFF:
            result = pull_staff_from_device(device)
        elif command == DeviceCommandType.PUSH_STAFF:
            result = push_staff_to_device(device)
        elif command == DeviceCommandType.PULL_ATTENDANCE:
            result = pull_attendance_from_device(device)
        else:
            result = {"ok": False, "detail": f"Unknown command: {command}"}

        cmd = DeviceCommand.objects.create(
            device=device,
            command=command,
            status=DeviceCommandStatus.COMPLETED if result.get("ok") else DeviceCommandStatus.FAILED,
            payload={},
            result=result,
            error_message="" if result.get("ok") else (result.get("detail") or result.get("message") or "")[:255],
            created_by=user if getattr(user, "is_authenticated", False) else None,
            sent_at=timezone.now(),
            completed_at=timezone.now(),
        )
        result["command_id"] = cmd.pk
        result["mode"] = "direct"
        return result

    # Remote / push-mode path: prepare payload and queue
    payload = {}
    if command == DeviceCommandType.PUSH_STAFF:
        payload = {"staff": _staff_payload_from_employees()}

    cmd = queue_command(device, command, payload=payload, user=user)
    return {
        "ok": True,
        "queued": True,
        "mode": "queued",
        "command_id": cmd.pk,
        "command": command,
        "message": (
            "Command queued. The device/bridge will execute it on the next "
            "poll of /api/v1/device/commands/."
        ),
        "staff_count": len(payload.get("staff", [])) if payload else None,
    }


@transaction.atomic
def mark_command_sent(cmd: DeviceCommand):
    if cmd.status == DeviceCommandStatus.PENDING:
        cmd.status = DeviceCommandStatus.SENT
        cmd.sent_at = timezone.now()
        cmd.save(update_fields=["status", "sent_at"])


def complete_command(cmd: DeviceCommand, *, ok: bool, result=None, error=""):
    cmd.status = DeviceCommandStatus.COMPLETED if ok else DeviceCommandStatus.FAILED
    cmd.result = result or {}
    cmd.error_message = (error or "")[:255]
    cmd.completed_at = timezone.now()
    cmd.save(update_fields=["status", "result", "error_message", "completed_at"])

    # Apply side-effects for remote results
    if ok and cmd.command == DeviceCommandType.PULL_STAFF:
        staff = (result or {}).get("staff") or (result or {}).get("users") or []
        if staff:
            save_staff_snapshots(cmd.device, staff)
    if ok and cmd.command == DeviceCommandType.PULL_ATTENDANCE:
        punches = (result or {}).get("punches") or (result or {}).get("attendance") or []
        if punches:
            from .biometrics import ingest_event, normalize_direction, normalize_method, parse_api_timestamp

            created = 0
            for item in punches:
                emp_no = item.get("employee_no") or item.get("staff_id") or item.get("user_id")
                if not emp_no:
                    continue
                _log, was_created = ingest_event(
                    device=cmd.device,
                    device_employee_no=str(emp_no),
                    timestamp=parse_api_timestamp(item.get("timestamp") or item.get("time")),
                    direction=normalize_direction(item.get("direction") or item.get("status")),
                    source=normalize_method(item.get("method") or item.get("source") or "api"),
                    event_id=str(item.get("event_id") or item.get("external_id") or ""),
                    raw_payload=item,
                )
                if was_created:
                    created += 1
            cmd.result = {**(result or {}), "ingested": created}
            cmd.save(update_fields=["result"])
