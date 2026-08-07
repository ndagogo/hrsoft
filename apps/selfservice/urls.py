from django.urls import path
from . import views

app_name = "selfservice"

urlpatterns = [
    path("", views.selfservice_hub, name="hub"),
    path("profile/", views.profile_update_create, name="profile_request"),
    path("attendance/", views.attendance_correction_create, name="attendance_request"),
    path("loan/", views.loan_request_create, name="loan_request"),
    path("training/", views.training_request_create, name="training_request"),
    path("approvals/", views.approvals_list, name="approvals"),
    path("approvals/<str:model>/<int:pk>/<str:action>/", views.approve_request, name="approve"),
]
