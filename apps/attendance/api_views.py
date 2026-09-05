import json
import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.permissions import permission_required
from .models import BiometricDevice
from .biometrics import process_webhook_payload, verify_webhook_token, pull_device_events, test_device_connection

logger = logging.getLogger("apps.attendance.biometrics")


@csrf_exempt
@require_POST
def biometric_webhook(request):
    """
    Legacy PUSH MODE endpoint (HikVision-shaped payloads).

    Auth: per-device webhook token via ?token= or X-Webhook-Token.
    Device is resolved by token first (works remotely / behind NAT), with
    source-IP matching kept as a fallback for older LAN-only setups.
    """
    token = request.GET.get("token") or request.headers.get("X-Webhook-Token", "")
    device = None
    if token:
        from .biometrics import resolve_device_from_token
        device = resolve_device_from_token(token)

    if not device:
        device_ip = request.META.get("REMOTE_ADDR")
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            device_ip = xff.split(",")[0].strip()
        device = BiometricDevice.objects.filter(ip_address=device_ip, is_active=True).first()
        if device and token and not verify_webhook_token(device, token):
            logger.warning("Webhook auth failed for device %s", device)
            return JsonResponse({"detail": "Invalid token"}, status=401)

    if not device:
        logger.warning("Webhook from unknown device")
        return JsonResponse({"detail": "Unknown device"}, status=403)

    if token and not verify_webhook_token(device, token):
        logger.warning("Webhook auth failed for device %s", device)
        return JsonResponse({"detail": "Invalid token"}, status=401)

    payload = None
    if request.content_type and "multipart/form-data" in request.content_type:
        raw = request.POST.get("event_log")
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
    if payload is None:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None

    if not payload:
        return JsonResponse({"detail": "No parseable event payload"}, status=400)

    log = process_webhook_payload(device, payload)
    return JsonResponse({"detail": "ok", "ingested": bool(log), "punch_id": log.pk if log else None})


@permission_required("manage_devices")
@require_POST
def trigger_manual_sync(request, pk):
    """Lets an Admin/HR Manager click 'Sync now' on a device in the UI (pull mode, on-demand)."""
    device = get_object_or_404(BiometricDevice, pk=pk)
    count = pull_device_events(device)
    device.refresh_from_db()
    if device.last_sync_status == "error":
        messages.error(request, f"Sync failed for {device.name}: {device.last_sync_message}")
    else:
        messages.success(request, f"Synced {count} new event(s) from {device.name}.")
    return redirect("attendance:devices")


@permission_required("manage_devices")
@require_POST
def test_device_connection_view(request, pk):
    """Live reachability check (ZKTeco TCP 4370 or HikVision ISAPI)."""
    device = get_object_or_404(BiometricDevice, pk=pk)
    ok, message = test_device_connection(device)
    device.last_sync_message = message[:255]
    device.last_sync_status = "ok" if ok else "error"
    update_fields = ["last_sync_message", "last_sync_status"]
    if ok:
        from django.utils import timezone
        device.last_seen_at = timezone.now()
        update_fields.append("last_seen_at")
    device.save(update_fields=update_fields)
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, f"Connection failed: {message}")
    return redirect("attendance:devices")


def _ui_device_action(request, pk, command):
    from .device_sync import execute_or_queue

    device = get_object_or_404(BiometricDevice, pk=pk)
    force_queue = request.POST.get("queue") == "1"
    try:
        result = execute_or_queue(device, command, user=request.user, force_queue=force_queue)
    except Exception as exc:
        logger.exception("Device action %s failed for device %s", command, pk)
        messages.error(
            request,
            f"Could not reach device {device.name} ({device.endpoint_label}): {exc}",
        )
        return redirect("attendance:devices")
    if result.get("ok"):
        messages.success(request, result.get("message") or f"{command} completed.")
    else:
        messages.error(request, result.get("detail") or result.get("message") or f"{command} failed.")
    return redirect("attendance:devices")


@permission_required("manage_devices")
@require_POST
def ui_pull_staff(request, pk):
    from .models import DeviceCommandType
    return _ui_device_action(request, pk, DeviceCommandType.PULL_STAFF)


@permission_required("manage_devices")
@require_POST
def ui_push_staff(request, pk):
    from .models import DeviceCommandType
    return _ui_device_action(request, pk, DeviceCommandType.PUSH_STAFF)


@permission_required("manage_devices")
@require_POST
def ui_pull_attendance(request, pk):
    from .models import DeviceCommandType
    return _ui_device_action(request, pk, DeviceCommandType.PULL_ATTENDANCE)
