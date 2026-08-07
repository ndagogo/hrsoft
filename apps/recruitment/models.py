"""
Enterprise Applicant Tracking System (ATS).

Standard hiring lifecycle:
  Requisition → Approval → Job posting → Applications → Screening →
  Interviews / Assessments → Offer → Hire (or Reject / Withdraw)
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


# ---------------------------------------------------------------------------
# Requisition (headcount request)
# ---------------------------------------------------------------------------


class RequisitionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_HR = "pending_hr", "Pending HR"
    PENDING_GM = "pending_gm", "Pending GM"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"
    FULFILLED = "fulfilled", "Fulfilled"


class EmploymentType(models.TextChoices):
    FULL_TIME = "full_time", "Full-time"
    PART_TIME = "part_time", "Part-time"
    CONTRACT = "contract", "Contract"
    TEMPORARY = "temporary", "Temporary"
    INTERN = "intern", "Internship"


class JobRequisition(models.Model):
    """Formal request to open a headcount (manager → HR → GM)."""

    title = models.CharField(max_length=150)
    department = models.ForeignKey(
        "employees.Department", on_delete=models.SET_NULL, null=True, related_name="job_requisitions"
    )
    branch = models.ForeignKey(
        "organization.Branch", on_delete=models.SET_NULL, null=True, blank=True, related_name="job_requisitions"
    )
    positions = models.PositiveSmallIntegerField(default=1)
    employment_type = models.CharField(
        max_length=20, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME
    )
    justification = models.TextField(help_text="Business case for this hire.")
    job_description = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    min_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    target_start_date = models.DateField(null=True, blank=True)
    is_replacement = models.BooleanField(default=False)
    replacement_for = models.CharField(max_length=150, blank=True)
    status = models.CharField(
        max_length=20, choices=RequisitionStatus.choices, default=RequisitionStatus.DRAFT
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="job_requisitions"
    )
    hr_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_reviewed_requisitions",
    )
    hr_reviewed_at = models.DateTimeField(null=True, blank=True)
    hr_note = models.CharField(max_length=255, blank=True)
    gm_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gm_reviewed_requisitions",
    )
    gm_reviewed_at = models.DateTimeField(null=True, blank=True)
    gm_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"REQ-{self.pk}: {self.title}"


# ---------------------------------------------------------------------------
# Vacancy / job posting
# ---------------------------------------------------------------------------


class VacancyStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    OPEN = "open", "Open"
    ON_HOLD = "on_hold", "On hold"
    CLOSED = "closed", "Closed"
    FILLED = "filled", "Filled"
    CANCELLED = "cancelled", "Cancelled"


class WorkMode(models.TextChoices):
    ONSITE = "onsite", "On-site"
    HYBRID = "hybrid", "Hybrid"
    REMOTE = "remote", "Remote"


class Vacancy(models.Model):
    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=180, unique=True, blank=True, null=True)
    requisition = models.ForeignKey(
        JobRequisition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vacancies",
    )
    department = models.ForeignKey(
        "employees.Department", on_delete=models.SET_NULL, null=True, related_name="vacancies"
    )
    branch = models.ForeignKey(
        "organization.Branch", on_delete=models.SET_NULL, null=True, blank=True, related_name="vacancies"
    )
    description = models.TextField()
    requirements = models.TextField(blank=True)
    responsibilities = models.TextField(blank=True)
    positions = models.PositiveSmallIntegerField(default=1)
    employment_type = models.CharField(
        max_length=20, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME
    )
    work_mode = models.CharField(max_length=20, choices=WorkMode.choices, default=WorkMode.ONSITE)
    min_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    show_salary = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=VacancyStatus.choices, default=VacancyStatus.DRAFT)
    posted_date = models.DateField(null=True, blank=True)
    closing_date = models.DateField(null=True, blank=True)
    is_internal = models.BooleanField(default=True, help_text="Visible to employees.")
    is_public = models.BooleanField(default=False, help_text="Visible on careers portal.")
    hiring_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_vacancies",
    )
    recruiter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recruiter_vacancies",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_vacancies"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "vacancies"
        ordering = ["-posted_date", "-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:150] or "role"
            slug = base
            n = 1
            while Vacancy.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                n += 1
                slug = f"{base}-{n}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_accepting_applications(self):
        if self.status != VacancyStatus.OPEN:
            return False
        if self.closing_date and self.closing_date < timezone.localdate():
            return False
        return True

    @property
    def hired_count(self):
        return self.applications.filter(status=ApplicationStatus.HIRED).count()


# ---------------------------------------------------------------------------
# Applications / candidates
# ---------------------------------------------------------------------------


class ApplicationStatus(models.TextChoices):
    """Kanban pipeline stages (global ATS standard)."""

    NEW = "new", "Applied"
    SCREENING = "screening", "Screening"
    PHONE_SCREEN = "phone_screen", "Phone screen"
    INTERVIEW = "interview", "Interview"
    ASSESSMENT = "assessment", "Assessment"
    REFERENCE_CHECK = "reference_check", "Reference check"
    OFFER = "offer", "Offer"
    OFFER_ACCEPTED = "offer_accepted", "Offer accepted"
    HIRED = "hired", "Hired"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"


PIPELINE_ACTIVE = (
    ApplicationStatus.NEW,
    ApplicationStatus.SCREENING,
    ApplicationStatus.PHONE_SCREEN,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.ASSESSMENT,
    ApplicationStatus.REFERENCE_CHECK,
    ApplicationStatus.OFFER,
    ApplicationStatus.OFFER_ACCEPTED,
)

PIPELINE_ORDER = [c.value for c in ApplicationStatus]


class ApplicationSource(models.TextChoices):
    CAREERS = "careers", "Careers portal"
    INTERNAL = "internal", "Internal / referral"
    LINKEDIN = "linkedin", "LinkedIn"
    JOB_BOARD = "job_board", "Job board"
    AGENCY = "agency", "Recruitment agency"
    WALK_IN = "walk_in", "Walk-in"
    OTHER = "other", "Other"
    MANUAL = "manual", "Added by HR"


class Application(models.Model):
    vacancy = models.ForeignKey(Vacancy, on_delete=models.CASCADE, related_name="applications")
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    resume = models.FileField(upload_to="resumes/", blank=True, null=True)
    cover_letter = models.TextField(blank=True)
    linkedin_url = models.URLField(blank=True)
    current_employer = models.CharField(max_length=150, blank=True)
    current_title = models.CharField(max_length=150, blank=True)
    years_experience = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    expected_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notice_period_days = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(
        max_length=20, choices=ApplicationSource.choices, default=ApplicationSource.MANUAL
    )
    referral_name = models.CharField(max_length=150, blank=True)
    status = models.CharField(
        max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.NEW
    )
    rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    assigned_recruiter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_applications",
    )
    rejection_reason = models.CharField(max_length=255, blank=True)
    rejection_notes = models.TextField(blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    status_changed_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-applied_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["vacancy", "email"],
                name="uniq_application_vacancy_email",
            )
        ]

    def __str__(self):
        return f"{self.full_name} → {self.vacancy.title}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_terminal(self):
        return self.status in (
            ApplicationStatus.HIRED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        )


class ApplicationNote(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    body = models.TextField()
    is_private = models.BooleanField(default=True, help_text="Visible only to recruiters/HR.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ApplicationActivity(models.Model):
    """Audit trail for pipeline moves and key events."""

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    event = models.CharField(max_length=80)
    detail = models.TextField(blank=True)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "application activities"


# ---------------------------------------------------------------------------
# Interviews & scorecards
# ---------------------------------------------------------------------------


class InterviewType(models.TextChoices):
    PHONE = "phone", "Phone"
    VIDEO = "video", "Video"
    ONSITE = "onsite", "On-site"
    PANEL = "panel", "Panel"
    TECHNICAL = "technical", "Technical"
    HR = "hr", "HR"
    FINAL = "final", "Final / leadership"


class InterviewRecommendation(models.TextChoices):
    STRONG_HIRE = "strong_hire", "Strong hire"
    HIRE = "hire", "Hire"
    MAYBE = "maybe", "Maybe"
    NO_HIRE = "no_hire", "No hire"
    STRONG_NO = "strong_no", "Strong no"


class Interview(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="interviews")
    interview_type = models.CharField(
        max_length=20, choices=InterviewType.choices, default=InterviewType.VIDEO
    )
    round_number = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=120, blank=True)
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=60)
    location = models.CharField(max_length=200, blank=True)
    meeting_link = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    panel_members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="interview_panels"
    )
    rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    recommendation = models.CharField(
        max_length=20, choices=InterviewRecommendation.choices, blank=True
    )
    feedback = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scheduled_interviews",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_at"]

    def __str__(self):
        return f"Interview R{self.round_number} — {self.application.full_name}"


class InterviewScorecard(models.Model):
    interview = models.ForeignKey(Interview, on_delete=models.CASCADE, related_name="scorecards")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    technical_skills = models.PositiveSmallIntegerField(default=0)  # 1–5
    communication = models.PositiveSmallIntegerField(default=0)
    cultural_fit = models.PositiveSmallIntegerField(default=0)
    problem_solving = models.PositiveSmallIntegerField(default=0)
    overall = models.PositiveSmallIntegerField(default=0)
    recommendation = models.CharField(
        max_length=20, choices=InterviewRecommendation.choices, blank=True
    )
    comments = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("interview", "reviewer")]
        ordering = ["-submitted_at"]

    @property
    def average_score(self):
        scores = [
            self.technical_skills,
            self.communication,
            self.cultural_fit,
            self.problem_solving,
            self.overall,
        ]
        filled = [s for s in scores if s]
        return round(sum(filled) / len(filled), 1) if filled else 0


# ---------------------------------------------------------------------------
# Assessments & references
# ---------------------------------------------------------------------------


class AssessmentType(models.TextChoices):
    SKILLS = "skills", "Skills test"
    PSYCHOMETRIC = "psychometric", "Psychometric"
    CASE_STUDY = "case_study", "Case study"
    ASSIGNMENT = "assignment", "Take-home assignment"
    OTHER = "other", "Other"


class AssessmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    COMPLETED = "completed", "Completed"
    EXPIRED = "expired", "Expired"
    WAIVED = "waived", "Waived"


class Assessment(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="assessments")
    assessment_type = models.CharField(
        max_length=20, choices=AssessmentType.choices, default=AssessmentType.SKILLS
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    max_score = models.DecimalField(max_digits=5, decimal_places=1, default=100)
    status = models.CharField(
        max_length=20, choices=AssessmentStatus.choices, default=AssessmentStatus.PENDING
    )
    result_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class ReferenceCheck(models.Model):
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="references"
    )
    referee_name = models.CharField(max_length=120)
    referee_title = models.CharField(max_length=120, blank=True)
    referee_company = models.CharField(max_length=150, blank=True)
    referee_email = models.EmailField(blank=True)
    referee_phone = models.CharField(max_length=30, blank=True)
    relationship = models.CharField(max_length=80, blank=True)
    contacted_at = models.DateField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    would_rehire = models.BooleanField(null=True, blank=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------


class OfferStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SENT = "sent", "Sent"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"
    EXPIRED = "expired", "Expired"
    WITHDRAWN = "withdrawn", "Withdrawn"


class OfferLetter(models.Model):
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name="offer")
    salary_offered = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="NGN")
    start_date = models.DateField()
    employment_type = models.CharField(
        max_length=20, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME
    )
    probation_months = models.PositiveSmallIntegerField(default=3)
    benefits_summary = models.TextField(blank=True)
    offer_notes = models.TextField(blank=True)
    expires_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=OfferStatus.choices, default=OfferStatus.DRAFT)
    issued_at = models.DateField(null=True, blank=True)
    responded_at = models.DateField(null=True, blank=True)
    accepted = models.BooleanField(default=False)  # legacy compatibility
    document = models.FileField(upload_to="offers/", blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Offer — {self.application.full_name}"
