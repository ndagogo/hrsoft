from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("", views.reports_hub, name="hub"),
    path("builder/", views.report_builder, name="builder"),
    path("<int:pk>/", views.report_detail, name="detail"),
    path("<int:pk>/export/", views.report_export, name="export"),
]
