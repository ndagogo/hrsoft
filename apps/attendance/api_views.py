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
    PUSH MODE endpoint. Configure the HikVision device (Configuration >
    Network > Advanced Settings > HTTP Listening or an event-linkage
    "notify surveillance center" rule) to POST here.

    Accepts either:
      - multipart/form-data with an `event_log` field containing JSON
        (HikVision's classic ISAPI event-notification format), or
      - a raw JSON body (some firmware / "EventFormat: JSON" configs).

    Auth: a shared secret must be supplied either as `?token=...` query
    param or `X-Webhook-Token` header, checked against the device's
    configured webhook_token (or the platform-wide fallback secret).
    Device is identified by source IP.
    """
    device_ip = request.META.get("REMOTE_ADDR")
    device = BiometricDevice.objects.filter(ip_address=device_ip, is_active=True).first()

    if not device:
        logger.warning("Webhook from unknown device IP: %s", device_ip)
        return JsonResponse({"detail": "Unknown device"}, status=403)

    token = request.GET.get("token") or request.headers.get("X-Webhook-Token", "")
    if not verify_webhook_token(device, token):
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
    return JsonResponse({"detail": "ok", "ingested": bool(log)})


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
    device.save(update_fields=["last_sync_message", "last_sync_status"])
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, f"Connection failed: {message}")
    return redirect("attendance:devices")
