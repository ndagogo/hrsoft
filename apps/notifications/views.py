from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods

from .models import Notification


def _wants_json(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def _unread_count(user):
    return user.notifications.filter(is_read=False).count()


def _mark_notification_read(notif):
    if not notif.is_read:
        notif.is_read = True
        notif.save(update_fields=["is_read"])
        return True
    return False


@login_required
def notification_list(request):
    notifications = request.user.notifications.all()[:50]
    return render(request, "notifications/list.html", {"notifications": notifications})


@login_required
@require_http_methods(["GET", "POST"])
def open_notification(request, pk):
    """Mark one notification as read, then go to its link (or the list)."""
    notif = get_object_or_404(Notification, pk=pk, user=request.user)
    _mark_notification_read(notif)

    if _wants_json(request):
        return JsonResponse({
            "ok": True,
            "unread_count": _unread_count(request.user),
            "link": notif.link or "",
        })

    if notif.link:
        return redirect(notif.link)
    return redirect("notifications:list")


@login_required
@require_POST
def mark_read(request, pk):
    notif = get_object_or_404(Notification, pk=pk, user=request.user)
    _mark_notification_read(notif)
    unread = _unread_count(request.user)
    if _wants_json(request):
        return JsonResponse({"ok": True, "unread_count": unread})
    return redirect(request.META.get("HTTP_REFERER") or "notifications:list")


@login_required
@require_POST
def mark_all_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    if _wants_json(request):
        return JsonResponse({"ok": True, "unread_count": 0})
    return redirect(request.META.get("HTTP_REFERER") or "notifications:list")
