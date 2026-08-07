from django.urls import path
from . import api_views

app_name = "biometric_api"

urlpatterns = [
    path("biometric/webhook/", api_views.biometric_webhook, name="webhook"),
    path("biometric/devices/<int:pk>/sync/", api_views.trigger_manual_sync, name="manual_sync"),
    path("biometric/devices/<int:pk>/test/", api_views.test_device_connection_view, name="test_connection"),
]
