from django.contrib import admin
from .models import Department, Designation, Employee


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "head", "headcount")
    search_fields = ("name", "code")


@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "level")
    list_filter = ("department",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "full_name", "department", "designation", "status", "biometric_id")
    list_filter = ("status", "department", "employment_type")
    search_fields = ("employee_id", "user__first_name", "user__last_name", "biometric_id")
    autocomplete_fields = ["user", "manager"]
