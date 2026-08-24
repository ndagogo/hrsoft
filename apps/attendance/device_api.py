"""
Device-agnostic remote biometric attendance API.

Any terminal, bridge, or middleware can push punches over the internet using
a per-device Bearer token — no vendor-specific payload and no LAN IP matching
required.

Endpoints (see api_urls.py):
  POST /api/v1/biometric/punches/
  POST /api/v1/biometric/punches/batch/
  POST /api/v1/biometric/heartbeat/
  GET  /api/v1/biometric/employees/
"""
from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .biometrics import (
    extract_device_token,
    ingest_event,
    normalize_direction,
    normalize_method,
    parse_api_timestamp,
    resolve_device_from_token,
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
    if data is None:
        return {}
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
            "Missing device token. Send Authorization: Bearer <token> or X-Device-Token.",
            status=401,
        )

    device = resolve_device_from_token(token, device_id=device_id, serial_number=serial)
    if not device:
        logger.warning("Biometric API auth failed (device_id=%s serial=%s)", device_id, serial)
        return None, _json_error("Invalid device token or device not found", status=401)
    return device, None


def _punch_from_payload(device, item: dict):
    """Validate one punch dict and ingest it. Returns (result_dict, http_status)."""
    if not isinstance(item, dict):
        return {"ok": False, "detail": "Each punch must be an object"}, 400

    employee_no = (
        item.get("employee_no")
        or item.get("employee_id")
        or item.get("user_id")
        or item.get("biometric_id")
        or item.get("pin")
    )
    if employee_no in (None, ""):
        return {"ok": False, "detail": "employee_no is required"}, 400

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
        "employee_no": log.device_employee_no,
        "matched": log.matched,
        "employee_id": log.employee.employee_id if log.employee_id else None,
        "timestamp": log.timestamp.isoformat(),
        "direction": log.direction,
        "method": log.source,
    }, (201 if created else 200)


@csrf_exempt
@require_POST
def api_punch(request):
    """
    POST /api/v1/biometric/punches/

    Auth: Authorization: Bearer <device_webhook_token>

    Body:
    {
      "employee_no": "1024",
      "timestamp": "2026-08-12T09:02:14+01:00",
      "direction": "in",
      "method": "face",
      "event_id": "optional-idempotency-key"
    }
    """
    body = _parse_json_body(request)
    if body is None:
        return _json_error("Request body must be JSON")

    device, err = _authenticate_device(request, body)
    if err:
        return err

    # Allow either a bare punch object or {"punch": {...}}
    punch = body.get("punch") if isinstance(body.get("punch"), dict) else body
    result, status = _punch_from_payload(device, punch)
    if not result.get("ok"):
        return JsonResponse(result, status=status)

    device.last_sync_status = "ok"
    device.last_sync_message = "Remote API punch received"
    device.last_sync_at = timezone.now()
    device.last_seen_at = timezone.now()
    device.save(update_fields=["last_sync_status", "last_sync_message", "last_sync_at", "last_seen_at"])

    return JsonResponse({"ok": True, "device_id": device.pk, "device": device.name, **result}, status=status)


@csrf_exempt
@require_POST
def api_punch_batch(request):
    """
    POST /api/v1/biometric/punches/batch/

    Body:
    {
      "punches": [
        {"employee_no": "1024", "timestamp": "...", "direction": "in"},
        ...
      ]
    }
    """
    body = _parse_json_body(request)
    if body is None:
        return _json_error("Request body must be JSON")

    device, err = _authenticate_device(request, body)
    if err:
        return err

    punches = body.get("punches") or body.get("events") or body.get("records")
    if not isinstance(punches, list):
        return _json_error("punches must be a JSON array")
    if len(punches) == 0:
        return _json_error("punches array is empty")
    if len(punches) > MAX_BATCH_SIZE:
        return _json_error(f"Batch too large (max {MAX_BATCH_SIZE})", status=413)

    results = []
    created_count = 0
    duplicate_count = 0
    error_count = 0

    for index, item in enumerate(punches):
        result, status = _punch_from_payload(device, item)
        result["index"] = index
        results.append(result)
        if not result.get("ok"):
            error_count += 1
        elif result.get("created"):
            created_count += 1
        else:
            duplicate_count += 1

    device.last_sync_status = "ok" if error_count == 0 else "error"
    device.last_sync_message = (
        f"Batch API: {created_count} created, {duplicate_count} duplicates, {error_count} errors"
    )[:255]
    device.last_sync_at = timezone.now()
    device.last_seen_at = timezone.now()
    device.save(update_fields=["last_sync_status", "last_sync_message", "last_sync_at", "last_seen_at"])

    http_status = 207 if error_count and created_count else (400 if error_count and not created_count else 200)
    return JsonResponse(
        {
            "ok": error_count == 0,
            "device_id": device.pk,
            "device": device.name,
            "summary": {
                "total": len(punches),
                "created": created_count,
                "duplicates": duplicate_count,
                "errors": error_count,
            },
            "results": results,
        },
        status=http_status,
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_heartbeat(request):
    """
    GET|POST /api/v1/biometric/heartbeat/

    Lets a device/bridge confirm connectivity and report firmware/status.
    """
    body = {}
    if request.method == "POST":
        body = _parse_json_body(request)
        if body is None:
            return _json_error("Request body must be JSON")

    device, err = _authenticate_device(request, body)
    if err:
        return err

    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    firmware = body.get("firmware") or meta.get("firmware") or ""
    serial = body.get("serial_number") or body.get("device_serial") or ""

    update_fields = ["last_seen_at", "last_sync_status", "last_sync_message"]
    device.last_seen_at = timezone.now()
    device.last_sync_status = "ok"
    device.last_sync_message = f"Heartbeat OK{f' (fw {firmware})' if firmware else ''}"[:255]

    if serial and not device.serial_number:
        device.serial_number = str(serial)[:80]
        update_fields.append("serial_number")

    device.save(update_fields=update_fields)

    return JsonResponse(
        {
            "ok": True,
            "device_id": device.pk,
            "device": device.name,
            "server_time": timezone.now().isoformat(),
            "connection_mode": device.connection_mode,
            "brand": device.brand,
        }
    )


@csrf_exempt
@require_GET
def api_enrolled_employees(request):
    """
    GET /api/v1/biometric/employees/

    Returns employees with a biometric_id so a bridge/device can sync
    enrollment lists remotely.
    """
    device, err = _authenticate_device(request)
    if err:
        return err

    from apps.employees.models import Employee

    qs = (
        Employee.objects.filter(status="active")
        .exclude(biometric_id="")
        .select_related("user", "department")
        .order_by("biometric_id")
    )
    since = request.GET.get("updated_since")
    if since:
        qs = qs.filter(updated_at__gte=parse_api_timestamp(since))

    rows = [
        {
            "biometric_id": emp.biometric_id,
            "employee_id": emp.employee_id,
            "name": emp.user.get_full_name() or emp.user.username,
            "department": emp.department.name if emp.department_id else None,
            "face_enrolled": emp.face_enrolled,
            "fingerprint_enrolled": emp.fingerprint_enrolled,
            "updated_at": emp.updated_at.isoformat() if emp.updated_at else None,
        }
        for emp in qs[:5000]
    ]

    device.last_seen_at = timezone.now()
    device.save(update_fields=["last_seen_at"])

    return JsonResponse(
        {
            "ok": True,
            "device_id": device.pk,
            "count": len(rows),
            "employees": rows,
            "updated_since": since,
        }
    )
