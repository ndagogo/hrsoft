"""
Unified Biometric Device Hub API.

One base URL for full device ↔ HRMS communication:

  /api/v1/device/

Configure on the terminal / bridge:
  Cloud / Server URL : https://<host>/api/v1/device/
  Token              : <device webhook_token>

Device-facing (Bearer token):
  GET  /api/v1/device/                  Hub handshake + endpoint map
  POST /api/v1/device/heartbeat/        Keep-alive / register serial
  GET  /api/v1/device/staff/            Download staff IDs to enroll on device
  POST /api/v1/device/staff/            Upload staff IDs currently on device
  POST /api/v1/device/punches/          Upload clock-in / clock-out punches
  POST /api/v1/device/punches/batch/    Batch punch upload
  GET  /api/v1/device/commands/         Poll pending software commands
  POST /api/v1/device/commands/<id>/result/  Report command result

Software-facing (login + manage_devices):
  POST /api/v1/device/manage/<pk>/pull-staff/
  POST /api/v1/device/manage/<pk>/push-staff/
  POST /api/v1/device/manage/<pk>/pull-attendance/
  GET  /api/v1/device/manage/<pk>/punches/
  GET  /api/v1/device/manage/<pk>/staff/
  GET  /api/v1/device/manage/<pk>/status/
"""
from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.permissions import permission_required

from .biometrics import (
    extract_device_token,
    ingest_event,
    normalize_direction,
    normalize_method,
    parse_api_timestamp,
    resolve_device_from_token,
)
from .device_sync import (
    complete_command,
    execute_or_queue,
    mark_command_sent,
    save_staff_snapshots,
)
from .models import (
    BiometricDevice,
    DeviceCommand,
    DeviceCommandStatus,
    DeviceCommandType,
    DeviceStaffSnapshot,
    RawPunchLog,
)

logger = logging.getLogger("apps.attendance.biometrics")
MAX_BATCH_SIZE = 500


def _json_error(message, status=400, **extra):
    payload = {"ok": False, "detail": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _parse_json_body(request):
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _authenticate_device(request, body=None):
    body = body or {}
    token = extract_device_token(request)
    device_id = body.get("device_id") or request.GET.get("device_id")
    serial = body.get("device_serial") or body.get("serial_number") or request.GET.get("serial")
    try:
        device_id = int(device_id) if device_id not in (None, "") else None
    except (TypeError, ValueError):
        return None, _json_error("device_id must be an integer", status=400)
    if not token:
        return None, _json_error(
            "Missing device token. Use Authorization: Bearer <token> or X-Device-Token.",
            status=401,
        )
    device = resolve_device_from_token(token, device_id=device_id, serial_number=serial)
    if not device:
        return None, _json_error("Invalid device token or device not found", status=401)
    return device, None


def _touch_device(device, message="Device Hub activity"):
    device.last_seen_at = timezone.now()
    device.last_sync_status = "ok"
    device.last_sync_message = message[:255]
    device.save(update_fields=["last_seen_at", "last_sync_status", "last_sync_message"])


def _punch_result(device, item: dict):
    if not isinstance(item, dict):
        return {"ok": False, "detail": "Each punch must be an object"}, 400
    employee_no = (
        item.get("employee_no")
        or item.get("staff_id")
        or item.get("employee_id")
        or item.get("user_id")
        or item.get("biometric_id")
    )
    if employee_no in (None, ""):
        return {"ok": False, "detail": "employee_no / staff_id is required"}, 400

    timestamp = parse_api_timestamp(item.get("timestamp") or item.get("time") or item.get("punched_at"))
    direction = normalize_direction(item.get("direction") or item.get("status") or item.get("type"))
    method = normalize_method(item.get("method") or item.get("source") or item.get("verify_mode") or "api")
    event_id = str(item.get("event_id") or item.get("external_id") or item.get("id") or "").strip()

    log, created = ingest_event(
        device=device,
        device_employee_no=str(employee_no).strip(),
        timestamp=timestamp,
        direction=direction,
        source=method,
        event_id=event_id,
        raw_payload=item,
    )
    return {
        "ok": True,
        "created": created,
        "punch_id": log.pk,
        "event_id": log.event_id or None,
        "staff_id": log.device_employee_no,
        "matched": log.matched,
        "employee_id": log.employee.employee_id if log.employee_id else None,
        "timestamp": log.timestamp.isoformat(),
        "direction": log.direction,
        "clock": "clock_in" if log.direction == "in" else ("clock_out" if log.direction == "out" else "unknown"),
        "method": log.source,
    }, (201 if created else 200)


# ---------------------------------------------------------------------------
# Device-facing hub
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
def hub_root(request):
    """
    Single entry point to enter on the biometric device / bridge.
    GET  → handshake + endpoint catalogue
    POST → optional register/heartbeat with serial/firmware
    """
    body = {}
    if request.method == "POST":
        body = _parse_json_body(request)
        if body is None:
            return _json_error("Request body must be JSON")

    device, err = _authenticate_device(request, body)
    if err:
        return err

    if request.method == "POST":
        serial = body.get("serial_number") or body.get("device_serial") or ""
        firmware = body.get("firmware") or ""
        update_fields = []
        if serial and not device.serial_number:
            device.serial_number = str(serial)[:80]
            update_fields.append("serial_number")
        _touch_device(device, f"Hub handshake{f' fw={firmware}' if firmware else ''}")
        if update_fields:
            device.save(update_fields=update_fields)

    base = "/api/v1/device"
    return JsonResponse(
        {
            "ok": True,
            "hub": "HFDN HRMS Biometric Device Hub",
            "version": "1.0",
            "device_id": device.pk,
            "device": device.name,
            "brand": device.brand,
            "connection_mode": device.connection_mode,
            "server_time": timezone.now().isoformat(),
            "capabilities": [
                "pull_staff",
                "push_staff",
                "pull_attendance",
                "punches",
                "commands",
            ],
            "endpoints": {
                "handshake": f"{base}/",
                "heartbeat": f"{base}/heartbeat/",
                "staff_download": f"{base}/staff/",
                "staff_upload": f"{base}/staff/",
                "punches": f"{base}/punches/",
                "punches_batch": f"{base}/punches/batch/",
                "commands": f"{base}/commands/",
                "command_result": f"{base}/commands/{{id}}/result/",
            },
            "auth": "Authorization: Bearer <device_token>",
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def hub_heartbeat(request):
    body = {}
    if request.method == "POST":
        body = _parse_json_body(request)
        if body is None:
            return _json_error("Request body must be JSON")
    device, err = _authenticate_device(request, body)
    if err:
        return err

    pending = device.commands.filter(status=DeviceCommandStatus.PENDING).count()
    serial = (body or {}).get("serial_number") or (body or {}).get("device_serial") or ""
    if serial and not device.serial_number:
        device.serial_number = str(serial)[:80]
        device.save(update_fields=["serial_number"])
    _touch_device(device, "Heartbeat OK")

    return JsonResponse(
        {
            "ok": True,
            "device_id": device.pk,
            "device": device.name,
            "server_time": timezone.now().isoformat(),
            "pending_commands": pending,
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def hub_staff(request):
    """
    GET  → HRMS pushes staff IDs to the device (device downloads enrollment list)
    POST → Device reports its enrolled staff IDs (software pulls from device)
    """
    body = {}
    if request.method == "POST":
        body = _parse_json_body(request)
        if body is None:
            return _json_error("Request body must be JSON")

    device, err = _authenticate_device(request, body)
    if err:
        return err

    if request.method == "GET":
        from apps.employees.models import Employee

        qs = (
            Employee.objects.filter(status="active")
            .exclude(biometric_id="")
            .select_related("user", "department")
            .order_by("biometric_id")
        )
        staff = [
            {
                "staff_id": emp.biometric_id,
                "employee_id": emp.employee_id,
                "name": emp.user.get_full_name() or emp.user.username,
                "department": emp.department.name if emp.department_id else None,
            }
            for emp in qs[:5000]
        ]
        _touch_device(device, f"Staff list downloaded ({len(staff)})")
        return JsonResponse({"ok": True, "device_id": device.pk, "count": len(staff), "staff": staff})

    # POST — device uploads its local enrollment list
    staff = body.get("staff") or body.get("users") or body.get("employees")
    if not isinstance(staff, list):
        return _json_error("staff must be a JSON array")

    normalized = []
    for item in staff:
        if not isinstance(item, dict):
            continue
        sid = item.get("staff_id") or item.get("user_id") or item.get("employee_no") or item.get("biometric_id")
        if not sid:
            continue
        normalized.append(
            {
                "staff_id": str(sid).strip(),
                "name": item.get("name") or "",
                "card": item.get("card") or item.get("card_no") or "",
                "privilege": item.get("privilege") or "",
                "raw": item,
            }
        )
    saved = save_staff_snapshots(device, normalized)
    _touch_device(device, f"Staff list uploaded ({saved})")
    return JsonResponse({"ok": True, "device_id": device.pk, "saved": saved, "count": saved})


@csrf_exempt
@require_POST
def hub_punches(request):
    body = _parse_json_body(request)
    if body is None:
        return _json_error("Request body must be JSON")
    device, err = _authenticate_device(request, body)
    if err:
        return err

    punch = body.get("punch") if isinstance(body.get("punch"), dict) else body
    result, status = _punch_result(device, punch)
    if not result.get("ok"):
        return JsonResponse(result, status=status)
    device.last_sync_at = timezone.now()
    _touch_device(device, "Punch received via Device Hub")
    device.save(update_fields=["last_sync_at", "last_seen_at", "last_sync_status", "last_sync_message"])
    return JsonResponse({"ok": True, "device_id": device.pk, "device": device.name, **result}, status=status)


@csrf_exempt
@require_POST
def hub_punches_batch(request):
    body = _parse_json_body(request)
    if body is None:
        return _json_error("Request body must be JSON")
    device, err = _authenticate_device(request, body)
    if err:
        return err

    punches = body.get("punches") or body.get("attendance") or body.get("events") or body.get("records")
    if not isinstance(punches, list) or not punches:
        return _json_error("punches must be a non-empty JSON array")
    if len(punches) > MAX_BATCH_SIZE:
        return _json_error(f"Batch too large (max {MAX_BATCH_SIZE})", status=413)

    results = []
    created = duplicates = errors = 0
    for index, item in enumerate(punches):
        result, _status = _punch_result(device, item)
        result["index"] = index
        results.append(result)
        if not result.get("ok"):
            errors += 1
        elif result.get("created"):
            created += 1
        else:
            duplicates += 1

    device.last_sync_at = timezone.now()
    _touch_device(device, f"Batch punches: {created} created, {duplicates} dup, {errors} err")
    device.save(update_fields=["last_sync_at", "last_seen_at", "last_sync_status", "last_sync_message"])

    http_status = 207 if errors and created else (400 if errors and not created else 200)
    return JsonResponse(
        {
            "ok": errors == 0,
            "device_id": device.pk,
            "summary": {
                "total": len(punches),
                "created": created,
                "duplicates": duplicates,
                "errors": errors,
                "clock_ins": sum(1 for r in results if r.get("direction") == "in"),
                "clock_outs": sum(1 for r in results if r.get("direction") == "out"),
            },
            "results": results,
        },
        status=http_status,
    )


@csrf_exempt
@require_GET
def hub_commands(request):
    """Device/bridge polls for pending software commands."""
    device, err = _authenticate_device(request)
    if err:
        return err

    pending = list(
        device.commands.filter(status=DeviceCommandStatus.PENDING).order_by("created_at")[:20]
    )
    commands = []
    for cmd in pending:
        mark_command_sent(cmd)
        commands.append(
            {
                "id": cmd.pk,
                "command": cmd.command,
                "payload": cmd.payload,
                "created_at": cmd.created_at.isoformat(),
            }
        )
    _touch_device(device, f"Commands polled ({len(commands)} pending)")
    return JsonResponse({"ok": True, "device_id": device.pk, "commands": commands})


@csrf_exempt
@require_POST
def hub_command_result(request, pk):
    body = _parse_json_body(request)
    if body is None:
        return _json_error("Request body must be JSON")
    device, err = _authenticate_device(request, body)
    if err:
        return err

    cmd = get_object_or_404(DeviceCommand, pk=pk, device=device)
    ok = bool(body.get("ok", True))
    complete_command(
        cmd,
        ok=ok,
        result=body.get("result") or body,
        error=body.get("error") or body.get("detail") or "",
    )
    _touch_device(device, f"Command {cmd.command} {'completed' if ok else 'failed'}")
    return JsonResponse({"ok": True, "command_id": cmd.pk, "status": cmd.status})


# ---------------------------------------------------------------------------
# Software-facing manage API (session auth)
# ---------------------------------------------------------------------------

def _manage_force_queue(request):
    if request.POST.get("queue") == "1":
        return True
    if (request.content_type or "").startswith("application/json"):
        body = _parse_json_body(request) or {}
        return bool(body.get("queue"))
    return False


@permission_required("manage_devices")
@require_POST
def manage_pull_staff(request, pk):
    device = get_object_or_404(BiometricDevice, pk=pk)
    result = execute_or_queue(
        device, DeviceCommandType.PULL_STAFF, user=request.user, force_queue=_manage_force_queue(request)
    )
    return JsonResponse(result, status=200 if result.get("ok") else 400)


@permission_required("manage_devices")
@require_POST
def manage_push_staff(request, pk):
    device = get_object_or_404(BiometricDevice, pk=pk)
    result = execute_or_queue(
        device, DeviceCommandType.PUSH_STAFF, user=request.user, force_queue=_manage_force_queue(request)
    )
    return JsonResponse(result, status=200 if result.get("ok") else 400)


@permission_required("manage_devices")
@require_POST
def manage_pull_attendance(request, pk):
    device = get_object_or_404(BiometricDevice, pk=pk)
    result = execute_or_queue(
        device,
        DeviceCommandType.PULL_ATTENDANCE,
        user=request.user,
        force_queue=_manage_force_queue(request),
    )
    return JsonResponse(result, status=200 if result.get("ok") else 400)


@permission_required("manage_devices")
@require_GET
def manage_punches(request, pk):
    device = get_object_or_404(BiometricDevice, pk=pk)
    limit = min(int(request.GET.get("limit") or 50), 500)
    qs = (
        RawPunchLog.objects.filter(device=device)
        .select_related("employee__user")
        .order_by("-timestamp")[:limit]
    )
    direction = request.GET.get("direction")
    if direction in ("in", "out", "unknown"):
        qs = (
            RawPunchLog.objects.filter(device=device, direction=direction)
            .select_related("employee__user")
            .order_by("-timestamp")[:limit]
        )
    return JsonResponse(
        {
            "ok": True,
            "device_id": device.pk,
            "count": len(qs),
            "punches": [
                {
                    "punch_id": p.pk,
                    "staff_id": p.device_employee_no,
                    "direction": p.direction,
                    "clock": "clock_in" if p.direction == "in" else ("clock_out" if p.direction == "out" else "unknown"),
                    "timestamp": p.timestamp.isoformat(),
                    "method": p.source,
                    "matched": p.matched,
                    "employee_id": p.employee.employee_id if p.employee_id else None,
                    "employee_name": p.employee.user.get_full_name() if p.employee_id else None,
                }
                for p in qs
            ],
        }
    )


@permission_required("manage_devices")
@require_GET
def manage_staff(request, pk):
    device = get_object_or_404(BiometricDevice, pk=pk)
    rows = DeviceStaffSnapshot.objects.filter(device=device).select_related("linked_employee__user")
    return JsonResponse(
        {
            "ok": True,
            "device_id": device.pk,
            "count": rows.count(),
            "staff": [
                {
                    "staff_id": r.staff_id,
                    "name": r.name,
                    "card_no": r.card_no,
                    "linked": bool(r.linked_employee_id),
                    "employee_id": r.linked_employee.employee_id if r.linked_employee_id else None,
                    "employee_name": (
                        r.linked_employee.user.get_full_name() if r.linked_employee_id else None
                    ),
                    "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
                }
                for r in rows
            ],
        }
    )


@permission_required("manage_devices")
@require_GET
def manage_status(request, pk):
    device = get_object_or_404(BiometricDevice, pk=pk)
    pending = device.commands.filter(status=DeviceCommandStatus.PENDING).count()
    punches = RawPunchLog.objects.filter(device=device).count()
    staff = DeviceStaffSnapshot.objects.filter(device=device).count()
    return JsonResponse(
        {
            "ok": True,
            "device": {
                "id": device.pk,
                "name": device.name,
                "brand": device.brand,
                "connection_mode": device.connection_mode,
                "ip_address": device.ip_address,
                "port": device.port,
                "serial_number": device.serial_number,
                "is_active": device.is_active,
                "is_online": device.is_online,
                "connection_status": device.connection_status,
                "last_sync_at": device.last_sync_at.isoformat() if device.last_sync_at else None,
                "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
                "last_sync_status": device.last_sync_status,
                "last_sync_message": device.last_sync_message,
                "hub_url": "/api/v1/device/",
                "has_token": bool(device.webhook_token),
            },
            "stats": {
                "pending_commands": pending,
                "punch_logs": punches,
                "staff_on_device": staff,
            },
        }
    )
