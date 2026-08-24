import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.training.models


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0005_announcement_audience_targeting"),
        ("training", "0002_learning_development_tlms"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CourseLesson",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "video",
                    models.FileField(
                        blank=True,
                        help_text="Upload MP4, WebM, or MOV (recommended: H.264 MP4).",
                        upload_to=apps.training.models._training_video_upload_to,
                    ),
                ),
                (
                    "external_url",
                    models.URLField(
                        blank=True,
                        help_text="Optional external video link (YouTube, Vimeo, SharePoint, etc.) if not uploading a file.",
                    ),
                ),
                (
                    "duration_seconds",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Optional length in seconds (auto-filled from player when watched).",
                        null=True,
                    ),
                ),
                ("is_published", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "course",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lessons",
                        to="training.course",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="CourseLessonProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("watched_seconds", models.PositiveIntegerField(default=0)),
                ("percent", models.PositiveSmallIntegerField(default=0)),
                ("completed", models.BooleanField(default=False)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("last_watched_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="course_lesson_progress",
                        to="employees.employee",
                    ),
                ),
                (
                    "lesson",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="progress_records",
                        to="training.courselesson",
                    ),
                ),
            ],
            options={
                "ordering": ["lesson__sort_order", "lesson_id"],
                "unique_together": {("lesson", "employee")},
            },
        ),
        migrations.AlterField(
            model_name="trainingdocument",
            name="doc_type",
            field=models.CharField(
                choices=[
                    ("brochure", "Brochure"),
                    ("material", "Training Material"),
                    ("video", "Video"),
                    ("presentation", "Presentation"),
                    ("manual", "Manual"),
                    ("assessment", "Assessment"),
                    ("certificate", "Certificate"),
                    ("attendance", "Attendance Sheet"),
                    ("invoice", "Invoice"),
                    ("evaluation", "Evaluation Report"),
                    ("other", "Other"),
                ],
                default="material",
                max_length=30,
            ),
        ),
    ]
