"""Broadcast published announcements to targeted staff notification feeds."""

from django.utils.html import strip_tags
from django.utils.text import Truncator

from apps.notifications.models import Notification, NotificationCategory


def notify_staff_of_published_announcement(announcement, *, exclude_user=None):
    """
    Create an in-app notification for each staff member in the announcement
    audience so it appears in the notification bell / list.
    """
    qs = announcement.recipient_users()

    if exclude_user is not None:
        qs = qs.exclude(pk=getattr(exclude_user, "pk", exclude_user))

    preview = Truncator(strip_tags(announcement.content or "")).chars(120)
    priority_label = ""
    if hasattr(announcement, "get_priority_display"):
        priority_label = announcement.get_priority_display()

    if announcement.priority in ("high", "urgent"):
        title = f"[{priority_label}] {announcement.title}"
    else:
        title = f"New announcement: {announcement.title}"

    message = preview or "A new company announcement has been published."
    link = f"/announcements/{announcement.pk}/"

    notifications = [
        Notification(
            user=user,
            title=title[:200],
            message=message,
            category=NotificationCategory.ANNOUNCEMENT,
            link=link,
        )
        for user in qs.iterator(chunk_size=200)
    ]
    if not notifications:
        return 0
    Notification.objects.bulk_create(notifications, batch_size=200)
    return len(notifications)
