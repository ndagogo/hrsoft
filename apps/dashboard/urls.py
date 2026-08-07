from django.urls import path
from . import views, calendar_api

app_name = "dashboard"

urlpatterns = [
    path("", views.router, name="router"),
    path("calendar/events/", calendar_api.calendar_events, name="calendar_events"),
    path("admin/", views.admin_dashboard, name="admin"),
    path("hr/", views.hr_dashboard, name="hr"),
    path("manager/", views.manager_dashboard, name="manager"),
    path("payroll/", views.payroll_dashboard, name="payroll"),
    path("employee/", views.employee_dashboard, name="employee"),
]
