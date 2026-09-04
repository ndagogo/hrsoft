from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.permissions import permission_required

from .forms import HolidayForm, SystemSettingForm
from .models import Holiday, SystemSetting
from .services import ensure_default_settings


@login_required
@permission_required("manage_system_settings")
def settings_overview(request):
    ensure_default_settings()
    return render(request, "system_settings/overview.html", {
        "settings": SystemSetting.objects.all(),
        "holidays": Holiday.objects.select_related("branch").order_by("date"),
        "setting_form": SystemSettingForm(),
        "holiday_form": HolidayForm(),
    })


@login_required
@permission_required("manage_system_settings")
def setting_create(request):
    if request.method == "POST":
        form = SystemSettingForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Setting “{form.instance.key}” created.")
        else:
            messages.error(request, "Could not create setting. Check that the key is unique.")
    return redirect("system_settings:overview")


@login_required
@permission_required("manage_system_settings")
def setting_edit(request, pk):
    obj = get_object_or_404(SystemSetting, pk=pk)
    if request.method == "POST":
        form = SystemSettingForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, f"Setting “{form.instance.key}” updated.")
        else:
            messages.error(request, "Could not update setting. Check the form fields.")
    return redirect("system_settings:overview")


@login_required
@permission_required("manage_system_settings")
def setting_delete(request, pk):
    obj = get_object_or_404(SystemSetting, pk=pk)
    if request.method == "POST":
        key = obj.key
        obj.delete()
        messages.success(request, f"Setting “{key}” deleted.")
    return redirect("system_settings:overview")


@login_required
@permission_required("manage_system_settings")
def holiday_create(request):
    if request.method == "POST":
        form = HolidayForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Holiday “{form.instance.name}” added.")
        else:
            messages.error(request, "Could not add holiday. Check the form fields.")
    return redirect("system_settings:overview")


@login_required
@permission_required("manage_system_settings")
def holiday_edit(request, pk):
    obj = get_object_or_404(Holiday, pk=pk)
    if request.method == "POST":
        form = HolidayForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, f"Holiday “{form.instance.name}” updated.")
        else:
            messages.error(request, "Could not update holiday. Check the form fields.")
    return redirect("system_settings:overview")


@login_required
@permission_required("manage_system_settings")
def holiday_delete(request, pk):
    obj = get_object_or_404(Holiday, pk=pk)
    if request.method == "POST":
        name = obj.name
        obj.delete()
        messages.success(request, f"Holiday “{name}” deleted.")
    return redirect("system_settings:overview")
