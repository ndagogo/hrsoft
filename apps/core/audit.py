"""Audit trail helpers with field-level change tracking."""

from django.forms.models import model_to_dict


SENSITIVE_FIELDS = {"password", "secret", "webhook_token", "token"}


def serialize_instance(instance, fields=None):
    if instance is None:
        return {}
    data = model_to_dict(instance, fields=fields)
    cleaned = {}
    for key, value in data.items():
        if any(s in key.lower() for s in SENSITIVE_FIELDS):
            cleaned[key] = "[redacted]"
        elif hasattr(value, "isoformat"):
            cleaned[key] = value.isoformat()
        elif hasattr(value, "pk"):
            cleaned[key] = str(value.pk)
        else:
            cleaned[key] = value if value is None or isinstance(value, (str, int, float, bool)) else str(value)
    return cleaned


def diff_dicts(old: dict, new: dict) -> tuple[dict, dict, str]:
    old_diff, new_diff = {}, {}
    keys = set(old) | set(new)
    parts = []
    for key in sorted(keys):
        o, n = old.get(key), new.get(key)
        if o != n:
            old_diff[key] = o
            new_diff[key] = n
            parts.append(f"{key}: {o!r} → {n!r}")
    return old_diff, new_diff, "; ".join(parts)


def log_change(request, action, instance=None, old_data=None, new_data=None, path=""):
    from apps.rbac.models import AuditLog

    old_values, new_values, summary = {}, {}, ""
    if old_data is not None and new_data is not None:
        old_values, new_values, summary = diff_dicts(old_data, new_data)

    user = getattr(request, "user", None) if request else None
    ip = None
    if request:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")

    return AuditLog.objects.create(
        user=user if user and user.is_authenticated else None,
        action=action,
        path=path or (getattr(request, "path", "") if request else ""),
        status_code=200,
        ip_address=ip,
        model_name=instance._meta.label if instance else "",
        object_id=str(instance.pk) if instance and instance.pk else "",
        object_repr=str(instance)[:255] if instance else "",
        old_values=old_values,
        new_values=new_values,
        change_summary=summary,
    )


def snapshot_before_save(instance):
    if not instance.pk:
        return None
    try:
        old = instance.__class__.objects.get(pk=instance.pk)
        return serialize_instance(old)
    except instance.__class__.DoesNotExist:
        return None
