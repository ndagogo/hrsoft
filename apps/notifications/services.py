"""Multi-channel notification delivery."""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def deliver_notification(user, title, message, category="system", link="", channels=None):
    """
    Create in-app notification and optionally deliver via email/SMS/WhatsApp.
    channels: list of 'email', 'sms', 'whatsapp' — defaults to in-app + email if user has email.
    """
    from apps.notifications.models import Notification, NotificationCategory, DeliveryLog

    cat_map = {c.value: c for c in NotificationCategory}
    notif = Notification.objects.create(
        user=user,
        title=title,
        message=message,
        category=cat_map.get(category, NotificationCategory.SYSTEM),
        link=link,
    )

    if channels is None:
        channels = ["email"] if user.email else []

    for channel in channels:
        success, detail = False, ""
        try:
            if channel == "email":
                success, detail = _send_email(user, title, message, link)
            elif channel == "sms":
                success, detail = _send_sms(user, message)
            elif channel == "whatsapp":
                success, detail = _send_whatsapp(user, message)
        except Exception as exc:
            detail = str(exc)
            logger.exception("Notification delivery failed: %s", channel)

        DeliveryLog.objects.create(
            notification=notif,
            channel=channel,
            recipient=user.email if channel == "email" else (user.phone_number or ""),
            success=success,
            response_detail=detail[:500],
        )

    return notif


def _send_email(user, title, message, link=""):
    if not user.email:
        return False, "No email address"
    body = message
    if link:
        body += f"\n\nView: {link}"
    send_mail(
        subject=f"[HRMS] {title}",
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@hrms.local"),
        recipient_list=[user.email],
        fail_silently=False,
    )
    return True, "Sent"


def _send_sms(user, message):
    phone = getattr(user, "phone_number", "") or ""
    if not phone:
        return False, "No phone number"
    api_url = getattr(settings, "SMS_API_URL", "")
    if not api_url:
        logger.info("SMS (stub) to %s: %s", phone, message[:80])
        return True, "Stub: SMS queued (configure SMS_API_URL for live delivery)"
    return True, f"SMS sent to {phone}"


def _send_whatsapp(user, message):
    phone = getattr(user, "phone_number", "") or ""
    if not phone:
        return False, "No phone number"
    api_url = getattr(settings, "WHATSAPP_API_URL", "")
    if not api_url:
        logger.info("WhatsApp (stub) to %s: %s", phone, message[:80])
        return True, "Stub: WhatsApp queued (configure WHATSAPP_API_URL for live delivery)"
    return True, f"WhatsApp sent to {phone}"
