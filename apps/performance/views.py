from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core.permissions import permission_required
from .models import PerformanceReview, Goal, KPI


@login_required
@permission_required("view_performance")
def performance_overview(request):
    return render(request, "performance/overview.html", {
        "reviews": PerformanceReview.objects.select_related("employee__user").order_by("-year")[:20],
        "goals": Goal.objects.select_related("employee__user").filter(is_completed=False)[:15],
        "kpis": KPI.objects.filter(is_active=True),
    })
