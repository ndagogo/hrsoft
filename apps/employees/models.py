from django.db import models
from django.conf import settings
from django.urls import reverse


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    description = models.TextField(blank=True)
    branch = models.ForeignKey(
        "organization.Branch", on_delete=models.SET_NULL, null=True, blank=True, related_name="departments"
    )
    head = models.ForeignKey(
        "employees.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="headed_department",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def headcount(self):
        return self.employees.filter(status="active").count()


class Designation(models.Model):
    title = models.CharField(max_length=100, unique=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="designations")
    level = models.PositiveSmallIntegerField(default=1, help_text="Seniority level, 1 = entry level.")

    class Meta:
        ordering = ["department__name", "level"]

    def __str__(self):
        return f"{self.title} ({self.department.code})"


class EmploymentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ON_LEAVE = "on_leave", "On Leave"
    SUSPENDED = "suspended", "Suspended"
    TERMINATED = "terminated", "Terminated"
    RESIGNED = "resigned", "Resigned"


class EmploymentType(models.TextChoices):
    FULL_TIME = "full_time", "Full-Time"
    PART_TIME = "part_time", "Part-Time"
    CONTRACT = "contract", "Contract"
    INTERN = "intern", "Intern"


class Gender(models.TextChoices):
    MALE = "M", "Male"
    FEMALE = "F", "Female"
    OTHER = "O", "Other"


class Employee(models.Model):
    """
    The HR profile for a staff member. Linked 1:1 with the auth User for
    login/roles, but kept separate so HR data (salary, biometric IDs, bank
    details) isn't tangled with authentication concerns.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employee_profile"
    )
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name="employees")
    designation = models.ForeignKey(Designation, on_delete=models.SET_NULL, null=True, related_name="employees")
    manager = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="direct_reports"
    )
    branches = models.ManyToManyField(
        "organization.Branch",
        related_name="employees",
        blank=False,
        help_text="One or more branches this employee is assigned to. At least one is required.",
    )

    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    date_joined = models.DateField()
    employment_type = models.CharField(max_length=20, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME)
    status = models.CharField(max_length=20, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVE)

    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="Nigeria")
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)
    next_of_kin_name = models.CharField(max_length=100, blank=True)
    next_of_kin_phone = models.CharField(max_length=20, blank=True)
    next_of_kin_address = models.CharField(max_length=255, blank=True)

    # Identity documents
    national_id = models.CharField(max_length=30, blank=True)
    nin = models.CharField(max_length=20, blank=True, help_text="National Identification Number")
    passport_number = models.CharField(max_length=30, blank=True)
    passport_expiry = models.DateField(null=True, blank=True)
    signature = models.ImageField(upload_to="signatures/", blank=True, null=True)
    passport_photo = models.ImageField(upload_to="passports/", blank=True, null=True)

    # Contract
    contract_start = models.DateField(null=True, blank=True)
    contract_end = models.DateField(null=True, blank=True)

    # Payroll-relevant
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    tax_id = models.CharField(max_length=30, blank=True)

    # Biometric enrolment - must match the User ID enrolled on the ZKTeco / HikVision terminal
    biometric_id = models.CharField(
        max_length=50, blank=True, null=True, unique=True,
        help_text="User ID / Employee No. as enrolled on the biometric device (ZKTeco user_id).",
    )
    biometric_enrolled = models.BooleanField(default=False)
    face_enrolled = models.BooleanField(default=False)
    fingerprint_enrolled = models.BooleanField(default=False)

    leave_balance_days = models.PositiveSmallIntegerField(default=21)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee_id"]

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.employee_id})"

    def get_absolute_url(self):
        return reverse("employees:detail", args=[self.pk])

    @property
    def full_name(self):
        return self.user.get_full_name()

    @property
    def photo_url(self):
        """Prefer profile avatar, then passport photo."""
        if self.user.avatar:
            return self.user.avatar.url
        if self.passport_photo:
            return self.passport_photo.url
        return ""

    @property
    def branch_names(self):
        return ", ".join(self.branches.values_list("name", flat=True)) or "—"

    @property
    def primary_branch(self):
        return self.branches.order_by("-is_head_office", "name").first()


    @property
    def tenure_days(self):
        from django.utils import timezone
        return (timezone.now().date() - self.date_joined).days

    @property
    def contract_expiring_soon(self):
        if not self.contract_end:
            return False
        from django.utils import timezone
        return (self.contract_end - timezone.now().date()).days <= 30


class EmployeeEducation(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="education")
    institution = models.CharField(max_length=200)
    qualification = models.CharField(max_length=150)
    field_of_study = models.CharField(max_length=150, blank=True)
    start_year = models.PositiveIntegerField(null=True, blank=True)
    end_year = models.PositiveIntegerField(null=True, blank=True)
    grade = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["-end_year"]
        verbose_name_plural = "employee education"


class EmployeeCertification(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="certifications")
    name = models.CharField(max_length=200)
    issuing_body = models.CharField(max_length=150, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    credential_id = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["-issue_date"]


class EmployeeEmploymentHistory(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="employment_history")
    company_name = models.CharField(max_length=200)
    job_title = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    reason_for_leaving = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name_plural = "employee employment history"


class EmployeePromotion(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="promotions")
    from_designation = models.CharField(max_length=150, blank=True)
    to_designation = models.CharField(max_length=150)
    effective_date = models.DateField()
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["-effective_date"]


class EmployeeTransfer(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="transfers")
    from_department = models.CharField(max_length=150, blank=True)
    to_department = models.CharField(max_length=150)
    from_branch = models.CharField(max_length=150, blank=True)
    to_branch = models.CharField(max_length=150, blank=True)
    effective_date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-effective_date"]
