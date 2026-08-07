from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("", views.asset_dashboard, name="dashboard"),
    path("inventory/", views.asset_list, name="list"),
    path("register/", views.asset_create, name="create"),
    path("my/", views.my_assets, name="my"),
    path("requests/", views.asset_request_list, name="requests"),
    path("requests/new/", views.asset_request_create, name="request_create"),
    path("requests/<int:pk>/approve/", views.asset_request_approve, name="request_approve"),
    path("requests/<int:pk>/issue/", views.asset_request_issue, name="request_issue"),
    path("reports/", views.asset_reports, name="reports"),
    path("employee/<int:emp_pk>/", views.employee_assets, name="employee_assets"),
    path("offboarding/<int:emp_pk>/", views.offboarding_checklist, name="offboarding"),
    path("<int:pk>/", views.asset_detail, name="detail"),
    path("<int:pk>/edit/", views.asset_edit, name="edit"),
    path("<int:pk>/approve/", views.asset_approve, name="approve"),
    path("<int:pk>/assign/", views.asset_assign, name="assign"),
    path("<int:pk>/maintenance/", views.asset_maintenance_create, name="maintenance"),
    path("<int:pk>/dispose/", views.asset_dispose, name="dispose"),
    path("<int:pk>/qr/", views.asset_qr, name="qr"),
    path("assignments/<int:pk>/return/", views.assignment_return, name="return"),
    path("assignments/<int:pk>/transfer/", views.asset_transfer, name="transfer"),
    path("maintenance/<int:pk>/complete/", views.maintenance_complete, name="maintenance_complete"),
]
