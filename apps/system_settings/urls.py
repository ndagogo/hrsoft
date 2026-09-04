from django.urls import path
from . import views

app_name = "system_settings"

urlpatterns = [
    path("", views.settings_overview, name="overview"),
    path("keys/new/", views.setting_create, name="setting_create"),
    path("keys/<int:pk>/edit/", views.setting_edit, name="setting_edit"),
    path("keys/<int:pk>/delete/", views.setting_delete, name="setting_delete"),
    path("holidays/new/", views.holiday_create, name="holiday_create"),
    path("holidays/<int:pk>/edit/", views.holiday_edit, name="holiday_edit"),
    path("holidays/<int:pk>/delete/", views.holiday_delete, name="holiday_delete"),
]
