from django.conf import settings
from django.db import models


class ReviewPeriod(models.TextChoices):
    QUARTERLY = "quarterly", "Quarterly"
    ANNUAL = "annual", "Annual"


class ReviewStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SELF_ASSESSMENT = "self_assessment", "Self Assessment"
    SUPERVISOR_REVIEW = "supervisor_review", "Supervisor Review"
    COMPLETED = "completed", "Completed"


class KPI(models.Model):
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    department = models.ForeignKey("employees.Department", on_delete=models.SET_NULL, null=True, blank=True)
    weight = models.PositiveSmallIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title


class Goal(models.Model):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="goals")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_date = models.DateField()
    progress = models.PositiveSmallIntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class PerformanceReview(models.Model):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="performance_reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="reviews_given")
    period = models.CharField(max_length=20, choices=ReviewPeriod.choices, default=ReviewPeriod.ANNUAL)
    year = models.PositiveIntegerField()
    quarter = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.DRAFT)
    self_rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    supervisor_rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    final_rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    self_comments = models.TextField(blank=True)
    supervisor_comments = models.TextField(blank=True)
    promotion_recommended = models.BooleanField(default=False)
    training_recommended = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "-quarter"]
