from django.contrib import admin
from .models import PayrollPeriod, Payslip


class PayslipInline(admin.TabularInline):
    model = Payslip
    extra = 0
    readonly_fields = ("employee", "gross_pay", "total_deductions", "net_pay")
    can_delete = False


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "status", "total_net_pay")
    list_filter = ("status",)
    inlines = [PayslipInline]


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = ("employee", "period", "gross_pay", "total_deductions", "net_pay")
    list_filter = ("period",)
    search_fields = ("employee__employee_id",)
    autocomplete_fields = ["employee"]
