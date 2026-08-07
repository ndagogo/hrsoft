"""TOTP MFA helpers."""

import base64
import io
import secrets

import pyotp
import qrcode
from django.conf import settings
from django.utils import timezone


def generate_secret():
    return pyotp.random_base32()


def get_totp(secret):
    return pyotp.TOTP(secret)


def verify_token(secret, token):
    if not secret or not token:
        return False
    totp = get_totp(secret)
    return totp.verify(str(token).strip(), valid_window=1)


def provisioning_uri(user, secret):
    issuer = getattr(settings, "COMPANY_NAME", "HRMS")
    return get_totp(secret).provisioning_uri(name=user.email or user.username, issuer_name=issuer)


def qr_code_base64(user, secret):
    uri = provisioning_uri(user, secret)
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def get_or_create_device(user):
    from apps.accounts.models import MFADevice
    device, created = MFADevice.objects.get_or_create(user=user, defaults={"secret": generate_secret()})
    if created or not device.secret:
        device.secret = generate_secret()
        device.save(update_fields=["secret"])
    return device


def activate_device(device):
    device.is_active = True
    device.enabled_at = timezone.now()
    device.save(update_fields=["is_active", "enabled_at"])


def deactivate_device(user):
    from apps.accounts.models import MFADevice
    try:
        device = user.mfa_device
        device.is_active = False
        device.secret = generate_secret()
        device.save(update_fields=["is_active", "secret"])
    except MFADevice.DoesNotExist:
        pass
