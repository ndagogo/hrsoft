from django.urls import path
from . import views

app_name = "training"

urlpatterns = [
    path("", views.training_overview, name="overview"),
]
