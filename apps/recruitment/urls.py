from django.urls import path

from . import views

app_name = "recruitment"

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="dashboard"),
    # Requisitions
    path("requisitions/", views.requisition_list, name="requisitions"),
    path("requisitions/new/", views.requisition_create, name="requisition_create"),
    path("requisitions/<int:pk>/", views.requisition_detail, name="requisition_detail"),
    path("requisitions/<int:pk>/submit/", views.requisition_submit, name="requisition_submit"),
    path("requisitions/<int:pk>/hr/", views.requisition_hr_action, name="requisition_hr"),
    path("requisitions/<int:pk>/gm/", views.requisition_gm_action, name="requisition_gm"),
    # Vacancies
    path("vacancies/", views.vacancy_list, name="vacancies"),
    path("vacancies/new/", views.vacancy_create, name="vacancy_create"),
    path("vacancies/<int:pk>/", views.vacancy_detail, name="vacancy_detail"),
    path("vacancies/<int:pk>/edit/", views.vacancy_edit, name="vacancy_edit"),
    path("vacancies/<int:pk>/publish/", views.vacancy_publish, name="vacancy_publish"),
    path("vacancies/<int:pk>/close/", views.vacancy_close, name="vacancy_close"),
    # Applications / pipeline
    path("applications/", views.application_list, name="applications"),
    path("applications/new/", views.application_create, name="application_create"),
    path("applications/<int:pk>/", views.application_detail, name="application_detail"),
    path("applications/<int:pk>/status/", views.application_set_status, name="application_status"),
    path("applications/<int:pk>/notes/", views.application_add_note, name="application_note"),
    path(
        "applications/<int:pk>/interviews/",
        views.application_schedule_interview,
        name="application_interview",
    ),
    path(
        "applications/<int:pk>/assessments/",
        views.application_add_assessment,
        name="application_assessment",
    ),
    path(
        "applications/<int:pk>/references/",
        views.application_add_reference,
        name="application_reference",
    ),
    path("applications/<int:pk>/offer/", views.application_save_offer, name="application_offer"),
    path("pipeline/", views.pipeline, name="pipeline"),
    # Interviews
    path("interviews/", views.interview_list, name="interviews"),
    path("interviews/<int:pk>/", views.interview_detail, name="interview_detail"),
    path("interviews/<int:pk>/feedback/", views.interview_feedback, name="interview_feedback"),
    path("interviews/<int:pk>/scorecard/", views.interview_scorecard, name="interview_scorecard"),
    # Offers
    path("offers/", views.offer_list, name="offers"),
    path("offers/<int:pk>/respond/", views.offer_respond, name="offer_respond"),
    # Public careers
    path("careers/", views.careers_list, name="careers"),
    path("careers/<slug:slug>/", views.careers_detail, name="careers_detail"),
    path("careers/<slug:slug>/thanks/", views.careers_thanks, name="careers_thanks"),
]
