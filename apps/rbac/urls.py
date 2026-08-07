from django.urls import path
from . import views

app_name = "rbac"

urlpatterns = [
    path("roles/", views.role_list, name="roles"),
    path("roles/new/", views.role_create, name="role_create"),
    path("roles/<int:pk>/builder/", views.role_builder, name="role_builder"),
    path("roles/<int:pk>/delete/", views.role_delete, name="role_delete"),
    path("permissions/", views.permission_list, name="permissions"),
    path("audit-log/", views.audit_log, name="audit_log"),
]
