from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class AnnouncementPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class AnnouncementStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending", "Pending approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AudienceType(models.TextChoices):
    ALL = "all", "All staff"
    DEPARTMENT = "department", "Selected department(s)"
    BRANCH = "branch", "Selected branch(es)"
    CADRE = "cadre", "Selected cadre(s)"


def _employee_profile_or_none(user):
    """Reverse OneToOne raises if the HR profile is missing — never use getattr()."""
    try:
        return user.employee_profile
    except Exception:
        return None


def _can_manage_announcements(user):
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True
    role = getattr(user, "role", None)
    if role and role.name in {"Admin", "HR Manager", "HR Officer", "General Manager"}:
        return True
    from apps.core.permissions import user_has_permission
    return user_has_permission(user, "create_announcement") or user_has_permission(
        user, "approve_announcement"
    )


class AnnouncementQuerySet(models.QuerySet):
    def published(self):
        now = timezone.now()
        return self.filter(
            status=AnnouncementStatus.APPROVED,
            is_active=True,
        ).filter(
            Q(published_at__isnull=True) | Q(published_at__lte=now)
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))

    def visible_to(self, user):
        """Published announcements the given user is allowed to see."""
        qs = self.published()
        if not user or not user.is_authenticated:
            return qs.none()
        # Creators/approvers need the full feed; audience targeting is for staff inbox.
        if _can_manage_announcements(user):
            return qs

        profile = _employee_profile_or_none(user)
        audience_q = Q(audience_type=AudienceType.ALL) | Q(audience_type="") | Q(author=user)
        if profile is not None:
            if profile.department_id:
                audience_q |= Q(
                    audience_type=AudienceType.DEPARTMENT,
                    departments=profile.department_id,
                )
            if profile.designation_id:
                audience_q |= Q(
                    audience_type=AudienceType.CADRE,
                    cadres=profile.designation_id,
                )
            branch_ids = list(profile.branches.values_list("id", flat=True))
            if branch_ids:
                audience_q |= Q(
                    audience_type=AudienceType.BRANCH,
                    branches__in=branch_ids,
                )
        return qs.filter(audience_q).distinct()


class Announcement(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="announcements_authored",
    )
    priority = models.CharField(
        max_length=10,
        choices=AnnouncementPriority.choices,
        default=AnnouncementPriority.NORMAL,
    )
    status = models.CharField(
        max_length=20,
        choices=AnnouncementStatus.choices,
        default=AnnouncementStatus.PENDING,
        db_index=True,
    )
    audience_type = models.CharField(
        max_length=20,
        choices=AudienceType.choices,
        default=AudienceType.ALL,
        db_index=True,
        help_text="Who should receive this announcement.",
    )
    departments = models.ManyToManyField(
        "employees.Department",
        blank=True,
        related_name="announcements",
    )
    branches = models.ManyToManyField(
        "organization.Branch",
        blank=True,
        related_name="announcements",
    )
    cadres = models.ManyToManyField(
        "employees.Designation",
        blank=True,
        related_name="announcements",
        help_text="Job titles / cadres (e.g. Manager, Officer).",
    )
    is_active = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="announcements_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AnnouncementQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_published(self):
        if self.status != AnnouncementStatus.APPROVED or not self.is_active:
            return False
        if self.published_at and self.published_at > timezone.now():
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    @property
    def audience_label(self):
        if self.audience_type == AudienceType.ALL:
            return "All staff"
        if self.audience_type == AudienceType.DEPARTMENT:
            names = list(self.departments.values_list("name", flat=True))
            return f"Department: {', '.join(names)}" if names else "Selected department(s)"
        if self.audience_type == AudienceType.BRANCH:
            names = list(self.branches.values_list("name", flat=True))
            return f"Branch: {', '.join(names)}" if names else "Selected branch(es)"
        if self.audience_type == AudienceType.CADRE:
            names = list(self.cadres.values_list("title", flat=True))
            return f"Cadre: {', '.join(names)}" if names else "Selected cadre(s)"
        return self.get_audience_type_display()

    def is_visible_to(self, user):
        """Whether a published announcement should be shown to this user."""
        if not self.is_published:
            return False
        if not user or not user.is_authenticated:
            return False
        if _can_manage_announcements(user):
            return True
        if self.author_id == getattr(user, "id", None):
            return True
        if self.audience_type in (AudienceType.ALL, "", None):
            return True

        profile = _employee_profile_or_none(user)
        if profile is None:
            return False

        if self.audience_type == AudienceType.DEPARTMENT:
            return bool(
                profile.department_id
                and self.departments.filter(pk=profile.department_id).exists()
            )
        if self.audience_type == AudienceType.BRANCH:
            return self.branches.filter(
                pk__in=profile.branches.values_list("id", flat=True)
            ).exists()
        if self.audience_type == AudienceType.CADRE:
            return bool(
                profile.designation_id
                and self.cadres.filter(pk=profile.designation_id).exists()
            )
        return False

    def recipient_users(self):
        """Active staff User queryset who should receive this announcement."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        qs = User.objects.filter(is_active=True)
        if hasattr(User, "is_active_employee"):
            qs = qs.filter(is_active_employee=True)

        if self.audience_type == AudienceType.ALL:
            return qs

        from apps.employees.models import EmploymentStatus

        emp_qs = qs.filter(
            employee_profile__isnull=False,
            employee_profile__status=EmploymentStatus.ACTIVE,
        )

        if self.audience_type == AudienceType.DEPARTMENT:
            dept_ids = list(self.departments.values_list("id", flat=True))
            if not dept_ids:
                return qs.none()
            return emp_qs.filter(employee_profile__department_id__in=dept_ids).distinct()

        if self.audience_type == AudienceType.BRANCH:
            branch_ids = list(self.branches.values_list("id", flat=True))
            if not branch_ids:
                return qs.none()
            return emp_qs.filter(employee_profile__branches__in=branch_ids).distinct()

        if self.audience_type == AudienceType.CADRE:
            cadre_ids = list(self.cadres.values_list("id", flat=True))
            if not cadre_ids:
                return qs.none()
            return emp_qs.filter(employee_profile__designation_id__in=cadre_ids).distinct()

        return qs.none()

    def submit_for_approval(self):
        self.status = AnnouncementStatus.PENDING
        self.submitted_at = timezone.now()
        self.approval_note = ""
        self.approved_by = None
        self.approved_at = None

    def approve(self, user, note=""):
        now = timezone.now()
        self.status = AnnouncementStatus.APPROVED
        self.approved_by = user
        self.approved_at = now
        self.approval_note = note or ""
        if not self.published_at:
            self.published_at = now
        self.is_active = True

    def reject(self, user, note=""):
        self.status = AnnouncementStatus.REJECTED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.approval_note = note or "Rejected"
        self.is_active = False


class AnnouncementAttachment(models.Model):
    announcement = models.ForeignKey(
        Announcement,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to="announcements/%Y/%m/")
    original_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=120, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return self.original_name or self.file.name

    @property
    def is_image(self):
        name = (self.original_name or self.file.name or "").lower()
        ctype = (self.content_type or "").lower()
        return ctype.startswith("image/") or name.endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        )
