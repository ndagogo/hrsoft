from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core.permissions import permission_required
from .models import SystemSetting, Holiday


@login_required
@permission_required("manage_system_settings")
def settings_overview(request):
    return render(request, "system_settings/overview.html", {
        "settings": SystemSetting.objects.all(),
        "holidays": Holiday.objects.order_by("date")[:30],
    })
