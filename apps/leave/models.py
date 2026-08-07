from django.conf import settings
from django.db import models
from django.utils import timezone


class LeaveType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    default_days_per_year = models.PositiveSmallIntegerField(default=21)
    requires_approval = models.BooleanField(default=True)
    color = models.CharField(max_length=20, default="#0ea5e9")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LeaveStatus(models.TextChoices):
    AWAITING_STANDIN = "awaiting_standin", "Awaiting Stand-in"
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class LeaveStandInStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class LeaveApprovalStage(models.TextChoices):
    HOD = "hod", "Head of Department"
    HR = "hr", "Human Resources"
    GM = "gm", "General Manager"


# Ordered approval chain (global practice for this HRMS)
APPROVAL_CHAIN = (
    LeaveApprovalStage.HOD,
    LeaveApprovalStage.HR,
    LeaveApprovalStage.GM,
)


class LeaveStepStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    PENDING = "pending", "Awaiting action"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    SKIPPED = "skipped", "Skipped"


class LeaveRequest(models.Model):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    handover_notes = models.TextField(
        blank=True,
        help_text="Tasks, contacts, and instructions for the stand-in officer.",
    )
    stand_in_employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stand_in_for_leave_requests",
        help_text="Nominated colleague to cover duties during leave.",
    )
    status = models.CharField(max_length=20, choices=LeaveStatus.choices, default=LeaveStatus.AWAITING_STANDIN)
    current_stage = models.CharField(
        max_length=10,
        choices=LeaveApprovalStage.choices,
        default=LeaveApprovalStage.HOD,
        blank=True,
        help_text="Active approval stage while status is pending.",
    )

    # Legacy single-review fields kept for compatibility / final decision summary
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="leave_reviews"
    )
    review_note = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee.employee_id} - {self.leave_type} ({self.start_date} to {self.end_date})"

    @property
    def days_requested(self):
        return (self.end_date - self.start_date).days + 1

    @property
    def status_label(self):
        if self.status == LeaveStatus.AWAITING_STANDIN:
            latest = self.active_stand_in_request
            if latest and latest.status == LeaveStandInStatus.DECLINED:
                return "Stand-in declined — select another colleague"
            if latest and latest.status == LeaveStandInStatus.PENDING:
                name = self.stand_in_employee.full_name if self.stand_in_employee else "colleague"
                return f"Awaiting stand-in acceptance ({name})"
            return "Awaiting stand-in acceptance"
        if self.status == LeaveStatus.PENDING and self.current_stage:
            stage = dict(LeaveApprovalStage.choices).get(self.current_stage, self.current_stage)
            return f"Pending — awaiting {stage}"
        return self.get_status_display()

    @property
    def resumption_date(self):
        from datetime import timedelta
        return self.end_date + timedelta(days=1)

    @property
    def stand_in_accepted(self):
        if not self.stand_in_employee_id:
            return True
        return self.stand_in_requests.filter(status=LeaveStandInStatus.ACCEPTED).exists()

    @property
    def active_stand_in_request(self):
        return self.stand_in_requests.order_by("-created_at").first()

    @property
    def approval_unlocked(self):
        return self.stand_in_accepted

    def timeline_steps(self):
        return self.approval_steps.order_by("sequence")


class LeaveApprovalStep(models.Model):
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name="approval_steps")
    stage = models.CharField(max_length=10, choices=LeaveApprovalStage.choices)
    sequence = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=LeaveStepStatus.choices, default=LeaveStepStatus.WAITING)
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leave_step_actions",
    )
    note = models.CharField(max_length=255, blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        unique_together = ("leave_request", "stage")

    def __str__(self):
        return f"{self.leave_request_id} · {self.get_stage_display()} · {self.get_status_display()}"

    def mark_pending(self):
        self.status = LeaveStepStatus.PENDING
        self.save(update_fields=["status"])

    def approve(self, user, note=""):
        self.status = LeaveStepStatus.APPROVED
        self.acted_by = user
        self.note = note or ""
        self.acted_at = timezone.now()
        self.save()

    def reject(self, user, note=""):
        self.status = LeaveStepStatus.REJECTED
        self.acted_by = user
        self.note = note or ""
        self.acted_at = timezone.now()
        self.save()


class LeaveStandInRequest(models.Model):
    """Stand-in coverage request — separate approval before managerial chain begins."""
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name="stand_in_requests")
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="leave_stand_in_outgoing",
    )
    stand_in_employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="leave_stand_in_incoming",
    )
    status = models.CharField(max_length=20, choices=LeaveStandInStatus.choices, default=LeaveStandInStatus.PENDING)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Stand-in: {self.stand_in_employee} for {self.employee} ({self.get_status_display()})"


class LeaveApprovalDocument(models.Model):
    leave_request = models.OneToOneField(LeaveRequest, on_delete=models.CASCADE, related_name="approval_document")
    reference_number = models.CharField(max_length=30, unique=True)
    verification_code = models.CharField(max_length=64, unique=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return self.reference_number

    @classmethod
    def build_reference(cls, leave_request):
        year = leave_request.created_at.year if leave_request.created_at else timezone.now().year
        return f"LV-{year}-{leave_request.pk:06d}"
