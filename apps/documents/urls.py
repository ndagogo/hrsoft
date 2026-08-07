from django.urls import path
from . import views

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="list"),
    path("my/", views.my_documents, name="my"),
    path("employee/<int:emp_pk>/", views.employee_documents, name="employee"),
    path("<int:pk>/view/", views.document_view, name="view"),
    path("<int:pk>/download/", views.document_download, name="download"),
    path("<int:pk>/delete/", views.document_delete, name="delete"),
]
