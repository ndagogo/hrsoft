from django.urls import path
from . import views

app_name = "leave"

urlpatterns = [
    path("my-requests/", views.my_leave_requests, name="my_requests"),
    path("my-requests/<int:pk>/", views.leave_request_detail, name="detail"),
    path("my-requests/<int:pk>/cancel/", views.leave_request_cancel, name="cancel"),
    path("my-requests/<int:pk>/renominate/", views.leave_renominate_standin, name="renominate"),
    path("my-requests/<int:pk>/letter/", views.leave_approval_letter, name="letter"),
    path("stand-in/", views.stand_in_requests, name="stand_in"),
    path("stand-in/<int:pk>/respond/", views.stand_in_respond, name="stand_in_respond"),
    path("verify/<str:ref>/", views.leave_verify, name="verify"),
    path("approvals/", views.leave_approvals, name="approvals"),
    path("approvals/<int:pk>/review/", views.leave_review, name="review"),
    path("types/", views.leave_type_list, name="types"),
]
