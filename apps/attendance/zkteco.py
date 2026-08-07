"""
ZKTeco attendance device client (TCP COMM port, typically 4370).

Uses the `pyzk` library to connect over the device's native TCP protocol
(shown on the terminal as TCP COMM. Port). Compatible with devices that
expose Ethernet settings like:

  IP Address: 192.168.1.201
  Subnet Mask: 255.255.255.0
  TCP COMM. Port: 4370
  DHCP: Off (static IP)
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("apps.attendance.biometrics")


def _zk_timeout():
    return int(settings.BIOMETRIC_SETTINGS.get("ZK_TIMEOUT_SECONDS", 10))


def connect_zk(device):
    """Open a ZK TCP session to the device. Caller must disconnect."""
    try:
        from zk import ZK
    except ImportError as exc:
        raise RuntimeError(
            "ZKTeco support requires the 'pyzk' package. Install with: pip install pyzk"
        ) from exc

    zk = ZK(
        str(device.ip_address),
        port=int(device.port or 4370),
        timeout=_zk_timeout(),
        password=int(getattr(device, "comm_key", 0) or 0),
        force_udp=False,
        ommit_ping=False,
    )
    return zk.connect()


def test_zk_connection(device) -> tuple[bool, str]:
    """Return (ok, message) after a lightweight connect + device info read."""
    conn = None
    try:
        conn = connect_zk(device)
        firmware = getattr(conn, "get_firmware_version", lambda: "")() or ""
        users = 0
        try:
            users = len(conn.get_users() or [])
        except Exception:
            pass
        serial = ""
        try:
            serial = conn.get_serialnumber() or ""
        except Exception:
            pass
        parts = [f"Connected to {device.ip_address}:{device.port}"]
        if firmware:
            parts.append(f"firmware {firmware}")
        if serial:
            parts.append(f"SN {serial}")
        if users:
            parts.append(f"{users} enrolled user(s)")
        return True, "; ".join(parts)
    except Exception as exc:
        logger.exception("ZK connection test failed for %s", device)
        return False, str(exc)[:255]
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def _aware(dt: datetime):
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def pull_zk_attendance(device, since=None) -> tuple[list[dict], str]:
    """
    Fetch attendance punches from a ZKTeco device.
    Returns (events, device_info_message).
    Each event: {user_id, timestamp, punch, status, raw}
    """
    conn = None
    events = []
    info = ""
    try:
        conn = connect_zk(device)
        try:
            info = f"SN {conn.get_serialnumber()}"
        except Exception:
            info = f"{device.ip_address}:{device.port}"

        # Disable device briefly for a consistent read (best practice with pyzk)
        try:
            conn.disable_device()
        except Exception:
            pass

        attendance = conn.get_attendance() or []
        since_aware = _aware(since) if since else None

        for record in attendance:
            # pyzk Attendance: user_id, timestamp, status, punch, uid
            ts = getattr(record, "timestamp", None)
            if not ts:
                continue
            ts = _aware(ts)
            if since_aware and ts <= since_aware:
                continue
            user_id = getattr(record, "user_id", None)
            if user_id is None:
                continue
            punch = getattr(record, "punch", None)
            status = getattr(record, "status", None)
            # Common mapping: punch 0/4 check-in, 1/5 check-out (varies by firmware)
            direction = "unknown"
            try:
                punch_i = int(punch) if punch is not None else -1
                if punch_i in (0, 4):
                    direction = "in"
                elif punch_i in (1, 5):
                    direction = "out"
            except (TypeError, ValueError):
                pass

            events.append(
                {
                    "user_id": str(user_id),
                    "timestamp": ts,
                    "direction": direction,
                    "punch": punch,
                    "status": status,
                    "raw": {
                        "user_id": str(user_id),
                        "timestamp": ts.isoformat(),
                        "punch": punch,
                        "status": status,
                        "uid": getattr(record, "uid", None),
                    },
                }
            )

        try:
            conn.enable_device()
        except Exception:
            pass

        return events, info
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass
