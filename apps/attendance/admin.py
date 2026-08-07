from django.contrib import admin
from .models import BiometricDevice, RawPunchLog, AttendanceRecord


@admin.register(BiometricDevice)
class BiometricDeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "ip_address", "connection_mode", "is_active", "last_sync_status", "last_sync_at")
    list_filter = ("brand", "connection_mode", "is_active")


@admin.register(RawPunchLog)
class RawPunchLogAdmin(admin.ModelAdmin):
    list_display = ("device_employee_no", "employee", "direction", "source", "timestamp", "matched", "device")
    list_filter = ("source", "direction", "matched", "device")
    search_fields = ("device_employee_no", "employee__employee_id")
    date_hierarchy = "timestamp"


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "check_in", "check_out", "status", "worked_hours", "is_manual_override")
    list_filter = ("status", "is_manual_override")
    search_fields = ("employee__employee_id",)
    date_hierarchy = "date"
    autocomplete_fields = ["employee"]
