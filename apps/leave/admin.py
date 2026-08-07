from django.contrib import admin
from .models import LeaveType, LeaveRequest, LeaveStandInRequest, LeaveApprovalDocument


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "default_days_per_year", "requires_approval")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "start_date", "end_date", "stand_in_employee", "status", "reviewed_by")
    list_filter = ("status", "leave_type")
    search_fields = ("employee__employee_id",)
    autocomplete_fields = ["employee", "stand_in_employee"]


@admin.register(LeaveStandInRequest)
class LeaveStandInRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "stand_in_employee", "status", "created_at", "responded_at")
    list_filter = ("status",)


@admin.register(LeaveApprovalDocument)
class LeaveApprovalDocumentAdmin(admin.ModelAdmin):
    list_display = ("reference_number", "leave_request", "generated_at")
    search_fields = ("reference_number",)
