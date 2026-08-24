from django.urls import path
from . import api_views, device_api, device_hub

app_name = "biometric_api"

urlpatterns = [
    # Legacy HikVision-shaped push webhook (IP + token)
    path("biometric/webhook/", api_views.biometric_webhook, name="webhook"),
    path("biometric/devices/<int:pk>/sync/", api_views.trigger_manual_sync, name="manual_sync"),
    path("biometric/devices/<int:pk>/test/", api_views.test_device_connection_view, name="test_connection"),

    # Legacy aliases (still supported)
    path("v1/biometric/punches/", device_api.api_punch, name="v1_punch"),
    path("v1/biometric/punches/batch/", device_api.api_punch_batch, name="v1_punch_batch"),
    path("v1/biometric/heartbeat/", device_api.api_heartbeat, name="v1_heartbeat"),
    path("v1/biometric/employees/", device_api.api_enrolled_employees, name="v1_employees"),

    # Unified Device Hub — enter this base URL on the biometric device / bridge
    path("v1/device/", device_hub.hub_root, name="hub_root"),
    path("v1/device/heartbeat/", device_hub.hub_heartbeat, name="hub_heartbeat"),
    path("v1/device/staff/", device_hub.hub_staff, name="hub_staff"),
    path("v1/device/punches/", device_hub.hub_punches, name="hub_punches"),
    path("v1/device/punches/batch/", device_hub.hub_punches_batch, name="hub_punches_batch"),
    path("v1/device/commands/", device_hub.hub_commands, name="hub_commands"),
    path("v1/device/commands/<int:pk>/result/", device_hub.hub_command_result, name="hub_command_result"),

    # Software → device control (session + manage_devices)
    path("v1/device/manage/<int:pk>/pull-staff/", device_hub.manage_pull_staff, name="manage_pull_staff"),
    path("v1/device/manage/<int:pk>/push-staff/", device_hub.manage_push_staff, name="manage_push_staff"),
    path(
        "v1/device/manage/<int:pk>/pull-attendance/",
        device_hub.manage_pull_attendance,
        name="manage_pull_attendance",
    ),
    path("v1/device/manage/<int:pk>/punches/", device_hub.manage_punches, name="manage_punches"),
    path("v1/device/manage/<int:pk>/staff/", device_hub.manage_staff, name="manage_staff"),
    path("v1/device/manage/<int:pk>/status/", device_hub.manage_status, name="manage_status"),

    # UI form actions (redirect + flash messages)
    path("biometric/devices/<int:pk>/pull-staff/", api_views.ui_pull_staff, name="ui_pull_staff"),
    path("biometric/devices/<int:pk>/push-staff/", api_views.ui_push_staff, name="ui_push_staff"),
    path(
        "biometric/devices/<int:pk>/pull-attendance/",
        api_views.ui_pull_attendance,
        name="ui_pull_attendance",
    ),
]
