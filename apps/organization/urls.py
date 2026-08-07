from django.urls import path
from . import views

app_name = "organization"

urlpatterns = [
    path("", views.org_overview, name="overview"),

    path("companies/new/", views.company_create, name="company_create"),
    path("companies/<int:pk>/edit/", views.company_edit, name="company_edit"),
    path("companies/<int:pk>/delete/", views.company_delete, name="company_delete"),

    path("regions/new/", views.region_create, name="region_create"),
    path("regions/<int:pk>/edit/", views.region_edit, name="region_edit"),
    path("regions/<int:pk>/delete/", views.region_delete, name="region_delete"),

    path("branches/new/", views.branch_create, name="branch_create"),
    path("branches/<int:pk>/edit/", views.branch_edit, name="branch_edit"),
    path("branches/<int:pk>/delete/", views.branch_delete, name="branch_delete"),

    path("units/new/", views.unit_create, name="unit_create"),
    path("units/<int:pk>/edit/", views.unit_edit, name="unit_edit"),
    path("units/<int:pk>/delete/", views.unit_delete, name="unit_delete"),
]
