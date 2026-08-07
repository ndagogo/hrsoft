from django.urls import path

from . import views

app_name = "announcements"

urlpatterns = [
    path("", views.announcement_list, name="list"),
    path("new/", views.announcement_create, name="create"),
    path("approvals/", views.announcement_approvals, name="approvals"),
    path("<int:pk>/", views.announcement_detail, name="detail"),
    path("<int:pk>/<str:action>/", views.announcement_review, name="review"),
]
