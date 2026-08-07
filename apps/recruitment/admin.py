from django.contrib import admin

from . import models


@admin.register(models.JobRequisition)
class JobRequisitionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "department", "positions", "status", "requested_by", "created_at")
    list_filter = ("status", "employment_type")
    search_fields = ("title",)


@admin.register(models.Vacancy)
class VacancyAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "status", "is_public", "posted_date", "closing_date")
    list_filter = ("status", "employment_type", "is_public")
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "slug")


@admin.register(models.Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("full_name", "vacancy", "email", "status", "source", "applied_at")
    list_filter = ("status", "source")
    search_fields = ("first_name", "last_name", "email")


@admin.register(models.Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = ("application", "interview_type", "scheduled_at", "completed")
    list_filter = ("interview_type", "completed")


@admin.register(models.OfferLetter)
class OfferLetterAdmin(admin.ModelAdmin):
    list_display = ("application", "salary_offered", "start_date", "status", "issued_at")
    list_filter = ("status",)


admin.site.register(models.ApplicationNote)
admin.site.register(models.ApplicationActivity)
admin.site.register(models.InterviewScorecard)
admin.site.register(models.Assessment)
admin.site.register(models.ReferenceCheck)
