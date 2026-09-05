from django.urls import path
from . import views

app_name = "employees"

urlpatterns = [
    path("", views.employee_list, name="list"),
    path("export/", views.employee_export, name="export"),
    path("import/", views.employee_import, name="import"),
    path("import/template/", views.employee_import_template, name="import_template"),
    path("new/", views.employee_create, name="create"),
    path("invite/", views.employee_invite, name="invite"),
    path("admissions/", views.admissions_queue, name="admissions"),
    path("admissions/<int:pk>/admit/", views.admit_invite, name="admit"),
    path("admissions/<int:pk>/reject/", views.reject_invite, name="reject"),
    path("<int:pk>/", views.employee_detail, name="detail"),
    path("<int:pk>/edit/", views.employee_edit, name="edit"),
    path("<int:pk>/deactivate/", views.employee_deactivate, name="deactivate"),

    path("departments/", views.department_list, name="departments"),
    path("departments/new/", views.department_create, name="department_create"),
    path("departments/<int:pk>/edit/", views.department_edit, name="department_edit"),
    path("designations/new/", views.designation_create, name="designation_create"),
]
