from django.urls import path
from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.attendance_list, name="list"),
    path("export/", views.attendance_export, name="export"),
    path("my-attendance/", views.my_attendance, name="my_attendance"),
    path("<int:pk>/override/", views.attendance_override, name="override"),

    path("devices/", views.device_list, name="devices"),
    path("devices/new/", views.device_create, name="device_create"),
    path("devices/<int:pk>/edit/", views.device_edit, name="device_edit"),
    path("devices/<int:pk>/delete/", views.device_delete, name="device_delete"),
    path("devices/link-biometric/", views.link_biometric_id, name="link_biometric"),
]