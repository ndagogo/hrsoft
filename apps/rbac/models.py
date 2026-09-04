from django.db import models


class PermissionCategory(models.TextChoices):
    EMPLOYEES = "employees", "Employees"
    ATTENDANCE = "attendance", "Attendance"
    LEAVE = "leave", "Leave"
    PAYROLL = "payroll", "Payroll"
    RBAC = "rbac", "Roles & Permissions"
    REPORTS = "reports", "Reports"
    SYSTEM = "system", "System"
    RECRUITMENT = "recruitment", "Recruitment"
    PERFORMANCE = "performance", "Performance"
    TRAINING = "training", "Training"
    ASSETS = "assets", "Assets"
    DOCUMENTS = "documents", "Documents"
    VISITORS = "visitors", "Visitors"
    ORGANIZATION = "organization", "Organization"
    ANNOUNCEMENTS = "announcements", "Announcements"
    TRANSPORT = "transport", "Transport"


class Permission(models.Model):
    """
    A single, granular privilege. Distinct from Django's built-in auth
    Permission model - this one is purpose-built for the HR domain and is
    what the Admin's role builder UI assigns to Roles.
    """
    codename = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=20, choices=PermissionCategory.choices)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class Role(models.Model):
    """
    A named bundle of Permissions. Admin can create/edit roles and assign
    permissions through the UI (RoleBuilder). Employees are linked to a
    single Role which drives both their dashboard and their access.
    """
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)
    is_system_role = models.BooleanField(
        default=False,
        help_text="System roles (Admin, HR Manager, etc.) cannot be deleted.",
    )
    dashboard_key = models.CharField(
        max_length=30,
        default="employee",
        help_text="Which dashboard template this role lands on, e.g. admin, hr, manager, payroll, employee.",
    )
    color = models.CharField(max_length=20, default="#6366f1", help_text="Badge color for this role.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def member_count(self):
        return self.users.count()


class AuditLog(models.Model):
    """Compliance trail with optional field-level change diffs."""
    user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="audit_logs"
    )
    action = models.CharField(max_length=20)
    path = models.CharField(max_length=255, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    model_name = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    change_summary = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp"]),
            models.Index(fields=["model_name", "object_id"]),
        ]

    def __str__(self):
        return f"{self.user} {self.action} {self.object_repr or self.path} @ {self.timestamp:%Y-%m-%d %H:%M}"

    @property
    def has_diff(self):
        return bool(self.old_values or self.new_values)
