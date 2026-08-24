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


class DeviceUnreachableError(Exception):
    """Raised when a ZKTeco terminal cannot be reached over the LAN."""


def _zk_timeout():
    return int(settings.BIOMETRIC_SETTINGS.get("ZK_TIMEOUT_SECONDS", 10))


def _zk_omit_ping() -> bool:
    # pyzk pings via ICMP before TCP connect; many networks block ICMP while
    # port 4370 still works. Default to omitting ping.
    return bool(settings.BIOMETRIC_SETTINGS.get("ZK_OMIT_PING", True))


def _friendly_zk_error(device, exc: BaseException) -> str:
    ip = device.ip_address or "?"
    port = device.port or 4370
    text = str(exc) or exc.__class__.__name__
    if "ping" in text.lower() or "can't reach" in text.lower():
        return (
            f"Cannot reach ZKTeco device at {ip}:{port}. "
            "Check that the terminal is powered on, on the same network/VPN as this server, "
            "and that TCP port 4370 is allowed through the firewall."
        )
    return f"ZKTeco connection failed ({ip}:{port}): {text}"[:255]


def connect_zk(device):
    """Open a ZK TCP session to the device. Caller must disconnect."""
    try:
        from zk import ZK
    except ImportError as exc:
        raise RuntimeError(
            "ZKTeco support requires the 'pyzk' package. Install with: pip install pyzk"
        ) from exc

    if not device.ip_address:
        raise DeviceUnreachableError("Device IP address is not set.")

    zk = ZK(
        str(device.ip_address),
        port=int(device.port or 4370),
        timeout=_zk_timeout(),
        password=int(getattr(device, "comm_key", 0) or 0),
        force_udp=False,
        ommit_ping=_zk_omit_ping(),
    )
    try:
        return zk.connect()
    except Exception as exc:
        raise DeviceUnreachableError(_friendly_zk_error(device, exc)) from exc


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


def pull_zk_users(device) -> tuple[list[dict], str]:
    """
    Read enrolled users from a ZKTeco device.
    Returns (users, info_message). Each user:
      {staff_id, name, privilege, card, uid, raw}
    Raises DeviceUnreachableError when the terminal cannot be contacted.
    """
    conn = None
    try:
        conn = connect_zk(device)
        try:
            conn.disable_device()
        except Exception:
            pass

        users = []
        for user in conn.get_users() or []:
            staff_id = str(getattr(user, "user_id", "") or "").strip()
            if not staff_id:
                continue
            users.append(
                {
                    "staff_id": staff_id,
                    "name": (getattr(user, "name", None) or "").strip(),
                    "privilege": str(getattr(user, "privilege", "") or ""),
                    "card": str(getattr(user, "card", "") or getattr(user, "card_number", "") or ""),
                    "uid": getattr(user, "uid", None),
                    "raw": {
                        "user_id": staff_id,
                        "name": getattr(user, "name", None),
                        "privilege": getattr(user, "privilege", None),
                        "card": getattr(user, "card", None),
                        "uid": getattr(user, "uid", None),
                    },
                }
            )

        try:
            conn.enable_device()
        except Exception:
            pass

        info = f"Read {len(users)} user(s) from {device.ip_address}:{device.port}"
        return users, info
    except DeviceUnreachableError:
        raise
    except Exception as exc:
        raise DeviceUnreachableError(_friendly_zk_error(device, exc)) from exc
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def push_zk_users(device, users: list[dict]) -> tuple[int, int, str]:
    """
    Enroll / update users on a ZKTeco device.
    Each user dict needs at least staff_id; optional name, privilege, card, password.
    Returns (ok_count, error_count, message).
    Raises DeviceUnreachableError when the terminal cannot be contacted.
    """
    conn = None
    ok = 0
    errors = 0
    try:
        conn = connect_zk(device)
        try:
            conn.disable_device()
        except Exception:
            pass

        for item in users:
            staff_id = str(item.get("staff_id") or item.get("user_id") or "").strip()
            if not staff_id:
                errors += 1
                continue
            try:
                # pyzk set_user(uid=None, name='', privilege=0, password='', group_id='', user_id='', card=0)
                kwargs = {
                    "name": (item.get("name") or "")[:24],
                    "privilege": int(item.get("privilege") or 0),
                    "password": str(item.get("password") or ""),
                    "user_id": staff_id,
                }
                card = item.get("card") or item.get("card_no") or 0
                try:
                    kwargs["card"] = int(card) if card not in (None, "") else 0
                except (TypeError, ValueError):
                    kwargs["card"] = 0
                if item.get("uid") is not None:
                    try:
                        kwargs["uid"] = int(item["uid"])
                    except (TypeError, ValueError):
                        pass
                conn.set_user(**kwargs)
                ok += 1
            except Exception as exc:
                errors += 1
                logger.warning("Failed to push user %s to %s: %s", staff_id, device, exc)

        try:
            conn.enable_device()
        except Exception:
            pass

        msg = f"Pushed {ok} user(s) to {device.ip_address}:{device.port}"
        if errors:
            msg += f" ({errors} failed)"
        return ok, errors, msg
    except DeviceUnreachableError:
        raise
    except Exception as exc:
        raise DeviceUnreachableError(_friendly_zk_error(device, exc)) from exc
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass
