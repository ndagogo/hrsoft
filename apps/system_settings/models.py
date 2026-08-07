from django.db import models


class SettingCategory(models.TextChoices):
    COMPANY = "company", "Company"
    PAYROLL = "payroll", "Payroll"
    LEAVE = "leave", "Leave"
    ATTENDANCE = "attendance", "Attendance"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    GENERAL = "general", "General"


class SystemSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    category = models.CharField(max_length=20, choices=SettingCategory.choices, default=SettingCategory.GENERAL)
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "key"]

    def __str__(self):
        return self.key


class Holiday(models.Model):
    name = models.CharField(max_length=100)
    date = models.DateField()
    is_recurring = models.BooleanField(default=False)
    branch = models.ForeignKey("organization.Branch", on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date"]
        verbose_name_plural = "holidays"

    def __str__(self):
        return f"{self.name} ({self.date})"
