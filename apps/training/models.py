"""
Learning & Development (T&LMS) models.

Pipeline:
  Need → Course → Program → Session → Enrollment → Attendance
       → Assessment → Completion → Certificate → Competency → Performance
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Catalog foundations
# ---------------------------------------------------------------------------

class TrainingCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=30, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "training categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class TrainingProvider(models.Model):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    website = models.URLField(blank=True)
    address = models.TextField(blank=True)
    bank_details = models.TextField(blank=True)
    rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TrainingInstructor(models.Model):
    class InstructorType(models.TextChoices):
        INTERNAL = "internal", "Internal"
        EXTERNAL = "external", "External"

    name = models.CharField(max_length=150)
    instructor_type = models.CharField(
        max_length=20, choices=InstructorType.choices, default=InstructorType.INTERNAL
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_instructor_profiles",
    )
    organization = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    specialization = models.CharField(max_length=200, blank=True)
    qualifications = models.TextField(blank=True)
    daily_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class DeliveryMethod(models.TextChoices):
    CLASSROOM = "classroom", "Classroom"
    VIRTUAL = "virtual", "Virtual (Teams / Zoom / Meet)"
    ELEARNING = "elearning", "E-learning (self-paced)"
    OJT = "ojt", "On-the-Job Training"
    WORKSHOP = "workshop", "Workshop"
    SEMINAR = "seminar", "Seminar"
    CONFERENCE = "conference", "Conference"
    COACHING = "coaching", "Coaching"
    MENTORING = "mentoring", "Mentoring"
    BLENDED = "blended", "Blended"


class TrainingType(models.TextChoices):
    INTERNAL = "internal", "Internal"
    EXTERNAL = "external", "External"
    CERTIFICATION = "certification", "Certification"
    APPRENTICESHIP = "apprenticeship", "Apprenticeship"
    MANDATORY = "mandatory", "Mandatory / Compliance"
    DEVELOPMENT = "development", "Development"


class DifficultyLevel(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    ADVANCED = "advanced", "Advanced"
    EXPERT = "expert", "Expert"


class Course(models.Model):
    """Reusable learning item in the organisation catalogue."""
    code = models.CharField(max_length=40, unique=True, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        TrainingCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="courses"
    )
    training_type = models.CharField(
        max_length=30, choices=TrainingType.choices, default=TrainingType.INTERNAL
    )
    delivery_method = models.CharField(
        max_length=30, choices=DeliveryMethod.choices, default=DeliveryMethod.CLASSROOM
    )
    duration_hours = models.PositiveSmallIntegerField(default=8)
    difficulty = models.CharField(
        max_length=20, choices=DifficultyLevel.choices, default=DifficultyLevel.INTERMEDIATE
    )
    provider = models.CharField(max_length=150, blank=True)  # legacy free-text
    provider_org = models.ForeignKey(
        TrainingProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="courses"
    )
    default_instructor = models.ForeignKey(
        TrainingInstructor, on_delete=models.SET_NULL, null=True, blank=True, related_name="courses"
    )
    budget_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="NGN")
    prerequisites = models.TextField(blank=True)
    target_audience = models.TextField(blank=True)
    is_mandatory = models.BooleanField(default=False)
    issues_certificate = models.BooleanField(default=True)
    certificate_validity_months = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Blank = does not expire"
    )
    pass_mark = models.PositiveSmallIntegerField(default=70)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    require_assessment = models.BooleanField(default=False)
    require_full_attendance = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return f"{self.code} — {self.title}" if self.code else self.title

    def save(self, *args, **kwargs):
        if not self.code:
            base = "".join(c for c in self.title.upper() if c.isalnum())[:8] or "CRS"
            self.code = f"{base}-{timezone.now().strftime('%y%m%d%H%M%S')[-6:]}"
        super().save(*args, **kwargs)

    @property
    def has_video_lessons(self):
        return self.lessons.filter(is_published=True).exists()

    @property
    def published_lesson_count(self):
        return self.lessons.filter(is_published=True).count()


def _training_video_upload_to(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp4"
    safe = "".join(c for c in (instance.title or "lesson")[:40] if c.isalnum() or c in "-_") or "lesson"
    return f"training_videos/{instance.course_id}/{safe}.{ext}"


class CourseLesson(models.Model):
    """A video (or linked) lesson within a course for self-paced e-learning."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    video = models.FileField(
        upload_to=_training_video_upload_to,
        blank=True,
        help_text="Upload MP4, WebM, or MOV (recommended: H.264 MP4).",
    )
    external_url = models.URLField(
        blank=True,
        help_text="Optional external video link (YouTube, Vimeo, SharePoint, etc.) if not uploading a file.",
    )
    duration_seconds = models.PositiveIntegerField(
        null=True, blank=True, help_text="Optional length in seconds (auto-filled from player when watched)."
    )
    is_published = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.course.code}: {self.title}"

    @property
    def has_playable_source(self):
        return bool(self.video) or bool(self.external_url)

    @property
    def duration_label(self):
        if not self.duration_seconds:
            return ""
        mins, secs = divmod(int(self.duration_seconds), 60)
        hours, mins = divmod(mins, 60)
        if hours:
            return f"{hours}h {mins:02d}m"
        return f"{mins}m {secs:02d}s"


class CourseLessonProgress(models.Model):
    """Per-employee watch progress for a course lesson."""

    lesson = models.ForeignKey(CourseLesson, on_delete=models.CASCADE, related_name="progress_records")
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="course_lesson_progress"
    )
    watched_seconds = models.PositiveIntegerField(default=0)
    percent = models.PositiveSmallIntegerField(default=0)
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_watched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("lesson", "employee")]
        ordering = ["lesson__sort_order", "lesson_id"]

    def __str__(self):
        return f"{self.employee_id} · {self.lesson_id} · {self.percent}%"


class TrainingProgram(models.Model):
    """Bundled curriculum of courses (e.g. Leadership Development Program)."""
    code = models.CharField(max_length=40, unique=True, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class TrainingProgramCourse(models.Model):
    program = models.ForeignKey(TrainingProgram, on_delete=models.CASCADE, related_name="program_courses")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="program_links")
    sequence = models.PositiveSmallIntegerField(default=1)
    is_required = models.BooleanField(default=True)

    class Meta:
        ordering = ["sequence", "id"]
        unique_together = ("program", "course")


# ---------------------------------------------------------------------------
# Sessions (scheduled instances of a course)
# ---------------------------------------------------------------------------

class SessionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class TrainingSchedule(models.Model):
    """
    A scheduled session of a course (kept name for migration compatibility).
    Think: "Advanced Excel – September 2026".
    """
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="schedules")
    title = models.CharField(max_length=200, blank=True, help_text="Optional session title override")
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    meeting_url = models.URLField(blank=True)
    trainer = models.CharField(max_length=150, blank=True)  # legacy free-text
    instructor = models.ForeignKey(
        TrainingInstructor, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions"
    )
    max_participants = models.PositiveSmallIntegerField(default=20)
    status = models.CharField(max_length=20, choices=SessionStatus.choices, default=SessionStatus.PUBLISHED)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "training session"
        verbose_name_plural = "training sessions"

    def __str__(self):
        label = self.title or self.course.title
        return f"{label} ({self.start_date})"

    @property
    def enrolled_count(self):
        return self.enrollments.exclude(
            status__in=[EnrollmentStatus.CANCELLED, EnrollmentStatus.WITHDRAWN, EnrollmentStatus.WAITLISTED]
        ).count()

    @property
    def waitlisted_count(self):
        return self.enrollments.filter(status=EnrollmentStatus.WAITLISTED).count()

    @property
    def available_seats(self):
        return max(0, self.max_participants - self.enrolled_count)

    @property
    def is_full(self):
        return self.available_seats <= 0


# ---------------------------------------------------------------------------
# Enrollment / attendance / assessment / certificates
# ---------------------------------------------------------------------------

class EnrollmentStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    APPROVED = "approved", "Approved"
    ENROLLED = "enrolled", "Enrolled"
    WAITLISTED = "waitlisted", "Waitlisted"
    ATTENDED = "attended", "Attended"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    WITHDRAWN = "withdrawn", "Withdrawn"
    NO_SHOW = "no_show", "No Show"
    CANCELLED = "cancelled", "Cancelled"


class TrainingEnrollment(models.Model):
    schedule = models.ForeignKey(TrainingSchedule, on_delete=models.CASCADE, related_name="enrollments")
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="training_enrollments"
    )
    status = models.CharField(max_length=20, choices=EnrollmentStatus.choices, default=EnrollmentStatus.ENROLLED)
    evaluation_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    attempt_number = models.PositiveSmallIntegerField(default=1)
    waitlist_position = models.PositiveSmallIntegerField(null=True, blank=True)
    completion_date = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    enrolled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        unique_together = ("schedule", "employee")
        ordering = ["-enrolled_at"]

    def __str__(self):
        return f"{self.employee} → {self.schedule}"


class AttendanceMark(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"
    EXCUSED = "excused", "Excused"


class TrainingAttendance(models.Model):
    enrollment = models.ForeignKey(TrainingEnrollment, on_delete=models.CASCADE, related_name="attendance_days")
    session_date = models.DateField()
    mark = models.CharField(max_length=20, choices=AttendanceMark.choices, default=AttendanceMark.PRESENT)
    check_in_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("enrollment", "session_date")
        ordering = ["session_date"]


class AssessmentType(models.TextChoices):
    PRE = "pre", "Pre-assessment"
    POST = "post", "Post-assessment"
    PRACTICAL = "practical", "Practical"
    FINAL = "final", "Final examination"


class TrainingAssessment(models.Model):
    enrollment = models.ForeignKey(TrainingEnrollment, on_delete=models.CASCADE, related_name="assessments")
    assessment_type = models.CharField(max_length=20, choices=AssessmentType.choices, default=AssessmentType.FINAL)
    score = models.DecimalField(max_digits=5, decimal_places=2)
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("100"))
    passed = models.BooleanField(default=False)
    attempt_number = models.PositiveSmallIntegerField(default=1)
    assessed_at = models.DateTimeField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True)
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-assessed_at"]


class CertificateStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    EXPIRED = "expired", "Expired"
    REVOKED = "revoked", "Revoked"
    SUPERSEDED = "superseded", "Superseded"


class TrainingCertificate(models.Model):
    enrollment = models.ForeignKey(
        TrainingEnrollment, on_delete=models.CASCADE, related_name="certificates"
    )
    certificate_number = models.CharField(max_length=50, unique=True)
    issued_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=CertificateStatus.choices, default=CertificateStatus.ACTIVE)
    version = models.PositiveSmallIntegerField(default=1)
    document = models.FileField(upload_to="certificates/", blank=True, null=True)
    verification_code = models.CharField(max_length=64, blank=True, db_index=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_date", "-version"]

    def __str__(self):
        return self.certificate_number

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())


# ---------------------------------------------------------------------------
# Requests & approvals
# ---------------------------------------------------------------------------

class RequestStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    MANAGER_REVIEW = "manager_review", "Manager Review"
    HR_REVIEW = "hr_review", "HR Review"
    FINANCE_REVIEW = "finance_review", "Finance Review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    SCHEDULED = "scheduled", "Scheduled"
    ENROLLED = "enrolled", "Enrolled"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    WITHDRAWN = "withdrawn", "Withdrawn"


class TrainingRequest(models.Model):
    """In-module training request (complements selfservice.TrainingRequest)."""
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="ld_training_requests"
    )
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, blank=True, related_name="requests"
    )
    course_title = models.CharField(max_length=200, blank=True)
    reason = models.TextField()
    expected_benefit = models.TextField(blank=True)
    preferred_date = models.DateField(null=True, blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    attachment = models.FileField(upload_to="training_requests/", blank=True, null=True)
    status = models.CharField(max_length=30, choices=RequestStatus.choices, default=RequestStatus.SUBMITTED)
    current_step = models.CharField(max_length=40, blank=True)
    schedule = models.ForeignKey(
        TrainingSchedule, on_delete=models.SET_NULL, null=True, blank=True, related_name="requests"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class TrainingApproval(models.Model):
    request = models.ForeignKey(TrainingRequest, on_delete=models.CASCADE, related_name="approvals")
    step = models.CharField(max_length=40)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decision = models.CharField(
        max_length=20,
        choices=[("approved", "Approved"), ("rejected", "Rejected"), ("pending", "Pending")],
        default="pending",
    )
    note = models.CharField(max_length=255, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


# ---------------------------------------------------------------------------
# Competencies & skills
# ---------------------------------------------------------------------------

class Competency(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=40, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=80, blank=True)
    max_level = models.PositiveSmallIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "competencies"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CourseCompetency(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="competency_links")
    competency = models.ForeignKey(Competency, on_delete=models.CASCADE, related_name="course_links")
    develops_to_level = models.PositiveSmallIntegerField(default=3)

    class Meta:
        unique_together = ("course", "competency")


class PositionCompetency(models.Model):
    """Competency requirement for a Designation (job position)."""
    designation = models.ForeignKey(
        "employees.Designation", on_delete=models.CASCADE, related_name="required_competencies"
    )
    competency = models.ForeignKey(Competency, on_delete=models.CASCADE, related_name="position_requirements")
    required_level = models.PositiveSmallIntegerField(default=3)

    class Meta:
        unique_together = ("designation", "competency")
        verbose_name_plural = "position competencies"


class EmployeeCompetency(models.Model):
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="competencies"
    )
    competency = models.ForeignKey(Competency, on_delete=models.CASCADE, related_name="employee_levels")
    current_level = models.PositiveSmallIntegerField(default=1)
    assessed_at = models.DateField(null=True, blank=True)
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    source = models.CharField(max_length=40, blank=True, help_text="manual / training / performance")
    notes = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee", "competency")
        verbose_name_plural = "employee competencies"


class TrainingNeed(models.Model):
    class NeedSource(models.TextChoices):
        COMPETENCY_GAP = "competency_gap", "Competency Gap"
        PERFORMANCE = "performance", "Performance Review"
        MANDATORY = "mandatory", "Mandatory Requirement"
        MANAGER = "manager", "Manager Request"
        EMPLOYEE = "employee", "Employee Request"
        ONBOARDING = "onboarding", "Onboarding"

    class NeedStatus(models.TextChoices):
        OPEN = "open", "Open"
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In Progress"
        CLOSED = "closed", "Closed"
        DISMISSED = "dismissed", "Dismissed"

    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="training_needs"
    )
    competency = models.ForeignKey(
        Competency, on_delete=models.SET_NULL, null=True, blank=True, related_name="needs"
    )
    recommended_course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, blank=True, related_name="needs"
    )
    source = models.CharField(max_length=30, choices=NeedSource.choices, default=NeedSource.COMPETENCY_GAP)
    required_level = models.PositiveSmallIntegerField(null=True, blank=True)
    current_level = models.PositiveSmallIntegerField(null=True, blank=True)
    gap = models.PositiveSmallIntegerField(default=0)
    rationale = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=NeedStatus.choices, default=NeedStatus.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-gap", "-created_at"]


# ---------------------------------------------------------------------------
# Learning paths & mandatory assignment rules
# ---------------------------------------------------------------------------

class LearningPath(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_designation = models.ForeignKey(
        "employees.Designation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_paths",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class LearningPathCourse(models.Model):
    path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name="path_courses")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="path_links")
    sequence = models.PositiveSmallIntegerField(default=1)
    is_required = models.BooleanField(default=True)

    class Meta:
        ordering = ["sequence"]
        unique_together = ("path", "course")


class TrainingAssignmentRule(models.Model):
    """Auto-assign mandatory courses based on org rules."""
    name = models.CharField(max_length=150)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="assignment_rules")
    department = models.ForeignKey(
        "employees.Department", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    designation = models.ForeignKey(
        "employees.Designation", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    branch = models.ForeignKey(
        "organization.Branch", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    employment_type = models.CharField(max_length=30, blank=True)
    apply_on_hire = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class TrainingAssignment(models.Model):
    class AssignmentStatus(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        OVERDUE = "overdue", "Overdue"
        WAIVED = "waived", "Waived"

    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="training_assignments"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="assignments")
    rule = models.ForeignKey(
        TrainingAssignmentRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="assignments"
    )
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=AssignmentStatus.choices, default=AssignmentStatus.ASSIGNED
    )
    is_mandatory = models.BooleanField(default=True)
    enrollment = models.ForeignKey(
        TrainingEnrollment, on_delete=models.SET_NULL, null=True, blank=True, related_name="assignments"
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-assigned_at"]
        indexes = [models.Index(fields=["employee", "course", "status"])]


# ---------------------------------------------------------------------------
# Evaluation, costs, documents, audit
# ---------------------------------------------------------------------------

class TrainingEvaluation(models.Model):
    enrollment = models.OneToOneField(
        TrainingEnrollment, on_delete=models.CASCADE, related_name="evaluation"
    )
    instructor_quality = models.PositiveSmallIntegerField(default=3)
    course_content = models.PositiveSmallIntegerField(default=3)
    materials = models.PositiveSmallIntegerField(default=3)
    venue = models.PositiveSmallIntegerField(default=3)
    relevance = models.PositiveSmallIntegerField(default=3)
    practical_usefulness = models.PositiveSmallIntegerField(default=3)
    overall = models.PositiveSmallIntegerField(default=3)
    comments = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)


class TrainingBudget(models.Model):
    year = models.PositiveIntegerField()
    department = models.ForeignKey(
        "employees.Department", on_delete=models.CASCADE, null=True, blank=True, related_name="training_budgets"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default="NGN")
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("year", "department")
        ordering = ["-year", "department__name"]


class TrainingExpense(models.Model):
    class ExpenseType(models.TextChoices):
        COURSE_FEE = "course_fee", "Course Fee"
        INSTRUCTOR = "instructor", "Instructor Fee"
        VENUE = "venue", "Venue"
        ACCOMMODATION = "accommodation", "Accommodation"
        TRANSPORT = "transport", "Transportation"
        MEALS = "meals", "Meals"
        MATERIALS = "materials", "Materials"
        CERTIFICATION = "certification", "Certification"
        OTHER = "other", "Other"

    schedule = models.ForeignKey(
        TrainingSchedule, on_delete=models.CASCADE, null=True, blank=True, related_name="expenses"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, null=True, blank=True, related_name="expenses")
    department = models.ForeignKey(
        "employees.Department", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    expense_type = models.CharField(max_length=30, choices=ExpenseType.choices, default=ExpenseType.COURSE_FEE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="NGN")
    description = models.CharField(max_length=255, blank=True)
    incurred_on = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-incurred_on"]


class TrainingDocument(models.Model):
    class DocType(models.TextChoices):
        BROCHURE = "brochure", "Brochure"
        MATERIAL = "material", "Training Material"
        VIDEO = "video", "Video"
        PRESENTATION = "presentation", "Presentation"
        MANUAL = "manual", "Manual"
        ASSESSMENT = "assessment", "Assessment"
        CERTIFICATE = "certificate", "Certificate"
        ATTENDANCE = "attendance", "Attendance Sheet"
        INVOICE = "invoice", "Invoice"
        EVALUATION = "evaluation", "Evaluation Report"
        OTHER = "other", "Other"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    schedule = models.ForeignKey(
        TrainingSchedule, on_delete=models.CASCADE, null=True, blank=True, related_name="documents"
    )
    title = models.CharField(max_length=200)
    doc_type = models.CharField(max_length=30, choices=DocType.choices, default=DocType.MATERIAL)
    file = models.FileField(upload_to="training_docs/")
    is_public_to_learners = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)


class TrainingAuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
