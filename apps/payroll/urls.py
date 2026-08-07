from django.urls import path
from . import views

app_name = "payroll"

urlpatterns = [
    path("periods/", views.payroll_period_list, name="periods"),
    path("periods/<int:pk>/", views.payroll_period_detail, name="period_detail"),
    path("periods/<int:pk>/run/", views.run_payroll, name="run"),
    path("periods/<int:pk>/submit-approval/", views.submit_for_approval, name="submit_approval"),
    path("periods/<int:pk>/approve/", views.approve_payroll, name="approve"),
    path("periods/<int:pk>/lock/", views.lock_payroll, name="lock"),
    path("periods/<int:pk>/mark-paid/", views.mark_period_paid, name="mark_paid"),
    path("periods/<int:pk>/bank-schedule/", views.bank_schedule, name="bank_schedule"),
    path("payslips/<int:pk>/adjust/", views.adjust_payslip, name="adjust"),
    path("payslips/<int:pk>/pdf/", views.payslip_pdf, name="payslip_pdf"),
    path("payslips/<int:pk>/", views.payslip_detail, name="payslip_detail"),
    path("my-payslips/", views.my_payslips, name="my_payslips"),
]
