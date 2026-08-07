"""
HikVision biometric device integration.

HikVision terminals (face/fingerprint access-control & time-attendance
units such as the DS-K1T series) expose two integration paths, and this
module implements both so the platform works regardless of network
topology or what the device supports:

1. PULL MODE (ISAPI polling)
   Django periodically calls the device's ISAPI endpoint
   `GET /ISAPI/AccessControl/AcsEvent` (HTTP Digest auth) to retrieve new
   access/attendance events since the last successful sync. Good when the
   device is on a private network the server can reach, and you don't
   want to expose your server to the device.

2. PUSH MODE (event webhook)
   The device is configured (via its own web UI: Configuration > Network
   > Advanced Settings > HTTP Listening, or "arming"/event-linkage rules)
   to POST each event as multipart/form-data (often containing an
   `event_log` JSON part) to our `/api/biometric/webhook/` endpoint in
   real time. Good for real-time dashboards and when the server is
   reachable from the device (e.g. same LAN, or via VPN/reverse tunnel).

Both paths converge on `ingest_event()`, which normalises a raw event
into a RawPunchLog row, matches it to an Employee by device_employee_no,
and then calls `recompute_daily_attendance()` to roll it up into the
day-level AttendanceRecord HR actually looks at.

NOTE ON CREDENTIALS: requests.auth.HTTPDigestAuth is used because
HikVision ISAPI defaults to Digest authentication. Some firmware/models
support Basic auth instead - if you find a device using Basic, swap the
auth object in `_device_session()`.
"""
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("apps.attendance.biometrics")


# ---------------------------------------------------------------------------
# Shared normalisation / ingestion
# ---------------------------------------------------------------------------

def ingest_event(*, device, device_employee_no, timestamp, direction="unknown", source="face", raw_payload=None):
    """
    Normalise one punch event (from either pull or push) into a
    RawPunchLog row, try to match it to an Employee, and roll the day's
    attendance up. Returns the created RawPunchLog.
    """
    from apps.employees.models import Employee
    from .models import RawPunchLog

    employee = Employee.objects.filter(biometric_id=str(device_employee_no)).select_related("user").first()

    log = RawPunchLog.objects.create(
        device=device,
        employee=employee,
        device_employee_no=str(device_employee_no),
        direction=direction,
        source=source,
        timestamp=timestamp,
        raw_payload=raw_payload or {},
        matched=employee is not None,
    )

    if employee:
        recompute_daily_attendance(employee, timestamp.date())
    else:
        logger.warning(
            "Unmatched biometric punch: device_employee_no=%s on device=%s at %s",
            device_employee_no, device, timestamp,
        )

    return log


@transaction.atomic
def recompute_daily_attendance(employee, day):
    """
    Rebuild the AttendanceRecord for `employee` on `day` from all
    RawPunchLog rows for that day: earliest punch = check_in, latest
    (different) punch = check_out. Idempotent - safe to call repeatedly
    as new punches arrive throughout the day.
    """
    from .models import RawPunchLog, AttendanceRecord, AttendanceStatus, PunchSource

    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    if timezone.is_naive(day_start):
        day_start = timezone.make_aware(day_start)
        day_end = timezone.make_aware(day_end)

    punches = list(
        RawPunchLog.objects.filter(employee=employee, timestamp__gte=day_start, timestamp__lt=day_end)
        .order_by("timestamp")
    )
    if not punches:
        return None

    check_in = punches[0].timestamp
    check_out = punches[-1].timestamp if len(punches) > 1 else None

    worked_hours = 0
    if check_out and check_out > check_in:
        worked_hours = round((check_out - check_in).total_seconds() / 3600, 2)

    workday_start_str = settings.BIOMETRIC_SETTINGS["DEFAULT_WORKDAY_START"]
    grace = settings.BIOMETRIC_SETTINGS["LATE_GRACE_MINUTES"]
    expected_start = datetime.combine(day, datetime.strptime(workday_start_str, "%H:%M").time())
    if timezone.is_naive(expected_start):
        expected_start = timezone.make_aware(expected_start)
    late_minutes = max(0, int((check_in - expected_start).total_seconds() / 60) - grace)

    status = AttendanceStatus.LATE if late_minutes > 0 else AttendanceStatus.PRESENT
    if day.weekday() >= 5:  # Sat/Sun
        status = AttendanceStatus.WEEKEND

    record, _ = AttendanceRecord.objects.update_or_create(
        employee=employee,
        date=day,
        defaults={
            "check_in": check_in,
            "check_out": check_out,
            "status": status,
            "source": punches[0].source,
            "worked_hours": worked_hours,
            "late_minutes": late_minutes,
            "is_manual_override": False,
        },
    )
    return record


# ---------------------------------------------------------------------------
# PUSH MODE - inbound webhook processing
# ---------------------------------------------------------------------------

def process_webhook_payload(device, payload: dict):
    """
    Parse a HikVision event-notification payload (already JSON-decoded
    from the `event_log` part of the multipart POST, or from a JSON body
    if the device/firmware supports `EventFormat: JSON`) and ingest it.

    Typical HikVision AccessControllerEvent shape:
    {
      "AccessControllerEvent": {
        "employeeNoString": "1024",
        "name": "Jane Doe",
        "currentVerifyMode": "faceOrFingerPrintOrPw",
        "attendanceStatus": "checkIn",   # checkIn / checkOut / breakOut / breakIn / overtimeIn / overtimeOut
        "majorEventType": 5,
        "subEventType": 75
      },
      "dateTime": "2026-06-29T09:02:14+01:00",
      "eventType": "AccessControllerEvent"
    }
    """
    event = payload.get("AccessControllerEvent") or payload.get("ANPR") or {}
    employee_no = event.get("employeeNoString") or event.get("employeeNo")
    if not employee_no:
        logger.info("Webhook payload from %s had no employeeNo, ignoring: %s", device, payload)
        return None

    dt_str = payload.get("dateTime") or payload.get("time")
    timestamp = _parse_device_datetime(dt_str) if dt_str else timezone.now()

    attendance_status = (event.get("attendanceStatus") or "").lower()
    if "checkin" in attendance_status or "in" in attendance_status:
        direction = "in"
    elif "checkout" in attendance_status or "out" in attendance_status:
        direction = "out"
    else:
        direction = "unknown"

    verify_mode = (event.get("currentVerifyMode") or "").lower()
    if "face" in verify_mode:
        source = "face"
    elif "fingerprint" in verify_mode or "fp" in verify_mode:
        source = "fingerprint"
    elif "card" in verify_mode:
        source = "card"
    elif "pw" in verify_mode or "password" in verify_mode:
        source = "password"
    else:
        source = "face"

    return ingest_event(
        device=device,
        device_employee_no=employee_no,
        timestamp=timestamp,
        direction=direction,
        source=source,
        raw_payload=payload,
    )


def _parse_device_datetime(dt_str):
    """HikVision typically sends ISO8601 with timezone offset, e.g. 2026-06-29T09:02:14+01:00."""
    try:
        dt = datetime.fromisoformat(dt_str)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt
    except (ValueError, TypeError):
        return timezone.now()


def verify_webhook_token(device, provided_token: str) -> bool:
    expected = device.webhook_token or settings.BIOMETRIC_SETTINGS["WEBHOOK_SHARED_SECRET"]
    return bool(provided_token) and provided_token == expected


# ---------------------------------------------------------------------------
# PULL MODE - ISAPI polling
# ---------------------------------------------------------------------------

def _device_session(device):
    """
    Build a `requests` session configured for HikVision ISAPI digest auth.
    Imports requests lazily so the rest of the app doesn't hard-require it
    if a deployment only ever uses push mode.
    """
    import requests
    from requests.auth import HTTPDigestAuth

    session = requests.Session()
    session.auth = HTTPDigestAuth(device.username, device.password)
    session.headers.update({"Accept": "application/json"})
    return session


def pull_device_events(device, since=None):
    """
    Poll a single device for attendance events since `since`
    (defaults to device.last_sync_at or 24h ago), ingest each into
    RawPunchLog/AttendanceRecord, and update the device's sync status.

    Routes by brand:
      - zkteco  → TCP COMM protocol (port 4370 via pyzk)
      - hikvision / other → HikVision ISAPI HTTP
    """
    since = since or device.last_sync_at or (timezone.now() - timedelta(hours=24))
    now = timezone.now()

    try:
        if device.brand == "zkteco":
            ingested = _pull_zkteco(device, since)
        else:
            ingested = _pull_hikvision(device, since, now)

        device.last_sync_at = now
        device.last_sync_status = "ok"
        device.last_sync_message = f"Synced {ingested} event(s) via {device.get_brand_display()}."
        device.save(update_fields=["last_sync_at", "last_sync_status", "last_sync_message"])
        logger.info("Pulled %s events from device %s", ingested, device)
        return ingested
    except Exception as exc:
        device.last_sync_status = "error"
        device.last_sync_message = str(exc)[:255]
        device.save(update_fields=["last_sync_status", "last_sync_message"])
        logger.error("Failed to pull events from device %s: %s", device, exc)
        return 0


def _pull_zkteco(device, since):
    from .zkteco import pull_zk_attendance

    events, _info = pull_zk_attendance(device, since=since)
    ingested = 0
    for event in events:
        ingest_event(
            device=device,
            device_employee_no=event["user_id"],
            timestamp=event["timestamp"],
            direction=event.get("direction", "unknown"),
            source="fingerprint",
            raw_payload=event.get("raw") or {},
        )
        ingested += 1
    return ingested


def _pull_hikvision(device, since, now):
    import requests

    url = f"{device.isapi_base_url}/AccessControl/AcsEvent?format=json"
    ingested = 0
    position = 0
    max_results = 30
    session = _device_session(device)

    while True:
        body = {
            "AcsEventCond": {
                "searchID": f"hrms-{int(now.timestamp())}",
                "searchResultPosition": position,
                "maxResults": max_results,
                "major": 5,
                "minor": 0,
                "startTime": since.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "endTime": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        }
        response = session.post(
            url,
            json=body,
            timeout=settings.BIOMETRIC_SETTINGS["ISAPI_TIMEOUT_SECONDS"],
        )
        response.raise_for_status()
        data = response.json()

        info_list = (data.get("AcsEvent", {}) or {}).get("InfoList", [])
        if not info_list:
            break

        for item in info_list:
            employee_no = item.get("employeeNoString") or item.get("employeeNo")
            if not employee_no:
                continue
            dt = _parse_device_datetime(item.get("time"))
            ingest_event(
                device=device,
                device_employee_no=employee_no,
                timestamp=dt,
                direction="unknown",
                source="face" if "face" in (item.get("currentVerifyMode") or "").lower() else "fingerprint",
                raw_payload=item,
            )
            ingested += 1

        num_matches = (data.get("AcsEvent", {}) or {}).get("numOfMatches", 0)
        position += max_results
        if position >= num_matches or len(info_list) < max_results:
            break

    return ingested


def test_device_connection(device) -> tuple[bool, str]:
    """Live connectivity check used by the Devices UI."""
    if device.brand == "zkteco":
        from .zkteco import test_zk_connection

        return test_zk_connection(device)

    # HikVision: lightweight GET against ISAPI System/deviceInfo
    import requests

    try:
        session = _device_session(device)
        url = f"{device.isapi_base_url}/System/deviceInfo"
        response = session.get(url, timeout=settings.BIOMETRIC_SETTINGS["ISAPI_TIMEOUT_SECONDS"])
        response.raise_for_status()
        return True, f"Connected to HikVision ISAPI at {device.ip_address}:{device.port}"
    except Exception as exc:
        return False, str(exc)[:255]


def pull_all_active_devices():
    """Convenience entrypoint for the management command / scheduled task (e.g. cron, Celery beat)."""
    from .models import BiometricDevice

    total = 0
    for device in BiometricDevice.objects.filter(is_active=True, connection_mode__in=["pull", "both"]):
        total += pull_device_events(device)
    return total
