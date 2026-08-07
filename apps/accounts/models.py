import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model. Authentication identity is separate from the
    Employee profile (apps.employees.Employee) so that not every user
    necessarily has a full HR record (e.g. a system integration account),
    though in practice every staff member gets both.
    """
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    role = models.ForeignKey(
        "rbac.Role", on_delete=models.SET_NULL, null=True, blank=True, related_name="users"
    )
    phone_number = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    must_change_password = models.BooleanField(default=False)
    is_active_employee = models.BooleanField(
        default=True, help_text="Set False when an employee offboards, without deleting their login history."
    )
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        first = self.first_name[:1] if self.first_name else self.username[:1]
        last = self.last_name[:1] if self.last_name else ""
        return f"{first}{last}".upper()

    @property
    def role_name(self):
        return self.role.name if self.role else ("Super Admin" if self.is_superuser else "Unassigned")

    @property
    def dashboard_key(self):
        if self.is_superuser:
            return "admin"
        return self.role.dashboard_key if self.role else "employee"

    @property
    def mfa_enabled(self):
        return hasattr(self, "mfa_device") and self.mfa_device.is_active


class LoginHistory(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="login_history")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    device = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=100, blank=True)
    success = models.BooleanField(default=True)
    login_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-login_at"]
        verbose_name_plural = "login history"


class MFADevice(models.Model):
    """Optional TOTP-based MFA — user scans QR code in authenticator app."""
    user = models.OneToOneField("accounts.User", on_delete=models.CASCADE, related_name="mfa_device")
    secret = models.CharField(max_length=32)
    is_active = models.BooleanField(default=False)
    enabled_at = models.DateTimeField(null=True, blank=True)
