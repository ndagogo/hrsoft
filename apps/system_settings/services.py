"""Read / seed application configuration stored in SystemSetting."""
from decimal import Decimal, InvalidOperation

from django.conf import settings as django_settings

from apps.rbac.catalog import DEFAULT_SYSTEM_SETTINGS
from apps.system_settings.models import SystemSetting


def ensure_default_settings():
    """Create missing catalog keys. Never overwrites values an admin already saved."""
    created = 0
    env_defaults = {
        "company_name": getattr(django_settings, "COMPANY_NAME", ""),
        "company_currency": getattr(django_settings, "COMPANY_CURRENCY", "NGN"),
        "company_currency_symbol": getattr(django_settings, "COMPANY_CURRENCY_SYMBOL", "₦"),
    }
    for key, value, category, description in DEFAULT_SYSTEM_SETTINGS:
        initial = env_defaults.get(key) or value
        _, was_created = SystemSetting.objects.get_or_create(
            key=key,
            defaults={"value": initial, "category": category, "description": description},
        )
        if was_created:
            created += 1
    return created


def get_setting(key, default=""):
    try:
        row = SystemSetting.objects.filter(key=key).values_list("value", flat=True).first()
    except Exception:
        return default
    if row is None or str(row).strip() == "":
        return default
    return str(row)


def get_settings_map(*keys):
    try:
        qs = SystemSetting.objects.all()
        if keys:
            qs = qs.filter(key__in=keys)
        return dict(qs.values_list("key", "value"))
    except Exception:
        return {}


def branding():
    rows = get_settings_map(
        "company_name", "company_currency", "company_currency_symbol",
    )
    return {
        "COMPANY_NAME": (rows.get("company_name") or "").strip()
        or getattr(django_settings, "COMPANY_NAME", "HRMS"),
        "COMPANY_CURRENCY": (rows.get("company_currency") or "").strip()
        or getattr(django_settings, "COMPANY_CURRENCY", "NGN"),
        "COMPANY_CURRENCY_SYMBOL": (rows.get("company_currency_symbol") or "").strip()
        or getattr(django_settings, "COMPANY_CURRENCY_SYMBOL", "₦"),
    }


def decimal_setting(key, default):
    raw = get_setting(key, str(default))
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(str(default))


def percent_rate(key, default_percent):
    """Stored as percent (7.5) → Decimal fraction (0.075)."""
    return decimal_setting(key, default_percent) / Decimal("100")
