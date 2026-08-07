from django.urls import path
from . import views

app_name = "performance"

urlpatterns = [
    path("", views.performance_overview, name="overview"),
]
