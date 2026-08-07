from django.conf import settings
from django.db import models


class NotificationCategory(models.TextChoices):
    SYSTEM = "system", "System"
    LEAVE = "leave", "Leave"
    PAYROLL = "payroll", "Payroll"
    ATTENDANCE = "attendance", "Attendance"
    RECRUITMENT = "recruitment", "Recruitment"
    ANNOUNCEMENT = "announcement", "Announcement"
    TASK = "task", "Task"
    APPROVAL = "approval", "Approval"


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=NotificationCategory.choices, default=NotificationCategory.SYSTEM)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at", "is_read"])]

    def __str__(self):
        return self.title


class DeliveryLog(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=20)
    recipient = models.CharField(max_length=255, blank=True)
    success = models.BooleanField(default=False)
    response_detail = models.CharField(max_length=500, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]
