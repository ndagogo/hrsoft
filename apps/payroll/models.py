from django.db import models
from django.conf import settings


class PayrollStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PROCESSED = "processed", "Processed"
    PAID = "paid", "Paid"


class PayrollApprovalStatus(models.TextChoices):
    NOT_SUBMITTED = "not_submitted", "Not Submitted"
    PENDING = "pending", "Pending Approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class PayrollPeriod(models.Model):
    """One payroll run, e.g. 'June 2026'."""
    name = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=PayrollStatus.choices, default=PayrollStatus.DRAFT)
    approval_status = models.CharField(
        max_length=20, choices=PayrollApprovalStatus.choices, default=PayrollApprovalStatus.NOT_SUBMITTED
    )
    is_locked = models.BooleanField(default=False, help_text="When locked, payslips cannot be edited or re-run.")
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="payroll_runs"
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    submitted_for_approval_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="payroll_approvals"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.CharField(max_length=255, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="payroll_locks"
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        unique_together = ("start_date", "end_date")

    def __str__(self):
        return self.name

    @property
    def total_net_pay(self):
        return self.payslips.aggregate(models.Sum("net_pay"))["net_pay__sum"] or 0

    @property
    def can_edit(self):
        return not self.is_locked and self.status != PayrollStatus.PAID

    @property
    def can_run(self):
        return self.can_edit and self.approval_status != PayrollApprovalStatus.PENDING


class Payslip(models.Model):
    period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE, related_name="payslips")
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="payslips")

    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    tax_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pension_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    late_penalty_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    gross_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    days_present = models.PositiveSmallIntegerField(default=0)
    days_absent = models.PositiveSmallIntegerField(default=0)
    days_late = models.PositiveSmallIntegerField(default=0)

    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period__start_date", "employee__employee_id"]
        unique_together = ("period", "employee")

    def __str__(self):
        return f"{self.employee.employee_id} - {self.period.name}"

    def compute(self, save=True):
        self.gross_pay = (
            self.basic_salary + self.housing_allowance + self.transport_allowance + self.other_allowance
        )
        self.total_deductions = (
            self.tax_deduction + self.pension_deduction + self.other_deduction + self.late_penalty_deduction
        )
        self.net_pay = self.gross_pay - self.total_deductions
        if save:
            self.save()
        return self.net_pay
