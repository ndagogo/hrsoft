from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core.permissions import permission_required
from .models import Course, TrainingSchedule, TrainingEnrollment


@login_required
@permission_required("view_training")
def training_overview(request):
    return render(request, "training/overview.html", {
        "courses": Course.objects.filter(is_active=True),
        "schedules": TrainingSchedule.objects.select_related("course").order_by("-start_date")[:15],
        "enrollments": TrainingEnrollment.objects.select_related("employee__user", "schedule__course").order_by("-enrolled_at")[:20],
    })
