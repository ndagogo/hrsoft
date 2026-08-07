from django.conf import settings
from django.db import models


class RequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class ProfileUpdateRequest(models.Model):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="profile_update_requests")
    field_name = models.CharField(max_length=80)
    current_value = models.CharField(max_length=255, blank=True)
    requested_value = models.CharField(max_length=255)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AttendanceCorrectionRequest(models.Model):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="attendance_corrections")
    date = models.DateField()
    current_status = models.CharField(max_length=30, blank=True)
    requested_check_in = models.TimeField(null=True, blank=True)
    requested_check_out = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class LoanRequest(models.Model):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="loan_requests")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    purpose = models.TextField()
    repayment_months = models.PositiveSmallIntegerField(default=12)
    status = models.CharField(max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TrainingRequest(models.Model):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="training_requests")
    course_title = models.CharField(max_length=200)
    justification = models.TextField()
    preferred_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
