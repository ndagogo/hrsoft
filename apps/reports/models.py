"""Custom report definitions and export."""

from django.conf import settings
from django.db import models


class ReportType(models.TextChoices):
    EMPLOYEES = "employees", "Employees"
    ATTENDANCE = "attendance", "Attendance"
    LEAVE = "leave", "Leave"
    PAYROLL = "payroll", "Payroll"
    DEPARTMENT = "department", "Department"


class ReportDefinition(models.Model):
    name = models.CharField(max_length=150)
    report_type = models.CharField(max_length=20, choices=ReportType.choices)
    description = models.TextField(blank=True)
    filters = models.JSONField(default=dict, blank=True)
    columns = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    is_shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name
