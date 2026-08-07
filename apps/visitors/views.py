from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.core.permissions import permission_required
from .models import Visitor


@login_required
@permission_required("view_visitors")
def visitor_list(request):
    today = timezone.now().date()
    return render(request, "visitors/list.html", {
        "visitors": Visitor.objects.select_related("host__user", "branch").all()[:50],
        "checked_in_today": Visitor.objects.filter(check_in__date=today).count(),
    })
