from django.db import models


class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    duration_hours = models.PositiveSmallIntegerField(default=8)
    provider = models.CharField(max_length=150, blank=True)
    budget_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class TrainingSchedule(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="schedules")
    start_date = models.DateField()
    end_date = models.DateField()
    location = models.CharField(max_length=200, blank=True)
    trainer = models.CharField(max_length=150, blank=True)
    max_participants = models.PositiveSmallIntegerField(default=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]


class EnrollmentStatus(models.TextChoices):
    ENROLLED = "enrolled", "Enrolled"
    ATTENDED = "attended", "Attended"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class TrainingEnrollment(models.Model):
    schedule = models.ForeignKey(TrainingSchedule, on_delete=models.CASCADE, related_name="enrollments")
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="training_enrollments")
    status = models.CharField(max_length=20, choices=EnrollmentStatus.choices, default=EnrollmentStatus.ENROLLED)
    evaluation_score = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("schedule", "employee")


class TrainingCertificate(models.Model):
    enrollment = models.OneToOneField(TrainingEnrollment, on_delete=models.CASCADE, related_name="certificate")
    certificate_number = models.CharField(max_length=50, unique=True)
    issued_date = models.DateField()
    document = models.FileField(upload_to="certificates/", blank=True, null=True)
