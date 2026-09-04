from django.conf import settings
from apps.system_settings.services import branding as live_branding


def site_branding(request):
    data = live_branding()
    data["IDLE_SESSION_TIMEOUT_SECONDS"] = getattr(settings, "IDLE_SESSION_TIMEOUT_SECONDS", 120)
    return data


def nav_permissions(request):
    """
    Exposes a `perms_set` (flat set of permission codenames the current
    user holds, via their role) to every template so sidebars/menus can do
    simple `{% if 'manage_employees' in perms_set %}` checks without extra
    queries per-template.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"perms_set": set(), "current_role": None, "unread_notifications": 0, "recent_notifications": []}

    if user.is_superuser:
        from apps.rbac.models import Permission

        perms = set(Permission.objects.values_list("codename", flat=True))
        role_name = "Super Admin"
    else:
        role = getattr(user, "role", None)
        if not role:
            return {"perms_set": set(), "current_role": None, "unread_notifications": 0, "recent_notifications": []}
        perms = set(role.permissions.values_list("codename", flat=True))
        role_name = role.name

    unread = user.notifications.filter(is_read=False).count()
    # Unread first, then newest — enough items to scroll through in the dropdown
    recent = list(
        user.notifications.all().order_by("is_read", "-created_at")[:25]
    )
    return {
        "perms_set": perms,
        "current_role": role_name,
        "unread_notifications": unread,
        "recent_notifications": recent,
    }
