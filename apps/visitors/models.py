from django.db import models


class VisitorStatus(models.TextChoices):
    EXPECTED = "expected", "Expected"
    CHECKED_IN = "checked_in", "Checked In"
    CHECKED_OUT = "checked_out", "Checked Out"
    CANCELLED = "cancelled", "Cancelled"


class Visitor(models.Model):
    full_name = models.CharField(max_length=150)
    company = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    id_number = models.CharField(max_length=50, blank=True)
    purpose = models.CharField(max_length=255)
    host = models.ForeignKey("employees.Employee", on_delete=models.SET_NULL, null=True, related_name="hosted_visitors")
    branch = models.ForeignKey("organization.Branch", on_delete=models.SET_NULL, null=True, blank=True)
    badge_number = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=20, choices=VisitorStatus.choices, default=VisitorStatus.EXPECTED)
    appointment_time = models.DateTimeField(null=True, blank=True)
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.full_name
