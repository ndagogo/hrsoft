from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class HRMSUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "email", "role", "is_active", "is_active_employee")
    list_filter = ("role", "is_active", "is_active_employee")
    search_fields = ("username", "first_name", "last_name", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("HRMS", {"fields": ("role", "phone_number", "avatar", "must_change_password", "is_active_employee")}),
    )
