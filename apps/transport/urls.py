from django.urls import path

from . import views

app_name = "transport"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("vehicles/", views.vehicle_list, name="vehicles"),
    path("vehicles/new/", views.vehicle_create, name="vehicle_create"),
    path("vehicles/<int:pk>/", views.vehicle_detail, name="vehicle_detail"),
    path("vehicles/<int:pk>/edit/", views.vehicle_edit, name="vehicle_edit"),
    path("vehicles/<int:pk>/documents/", views.vehicle_document_add, name="vehicle_document_add"),
    path("drivers/", views.driver_list, name="drivers"),
    path("drivers/new/", views.driver_create, name="driver_create"),
    path("drivers/<int:pk>/edit/", views.driver_edit, name="driver_edit"),
    path("rides/", views.ride_list, name="rides"),
    path("history/", views.transport_history, name="history"),
    path("rides/new/", views.ride_create, name="ride_create"),
    path("shuttles/new/", views.shuttle_create, name="shuttle_create"),
    path("api/geocode/", views.api_geocode, name="api_geocode"),
    path("api/route/", views.api_route, name="api_route"),
    path("rides/<int:pk>/", views.ride_detail, name="ride_detail"),
    path("rides/<int:pk>/submit/", views.ride_submit, name="ride_submit"),
    path("rides/<int:pk>/cancel/", views.ride_cancel, name="ride_cancel"),
    path("rides/<int:pk>/start/", views.ride_start, name="ride_start"),
    path("rides/<int:pk>/complete/", views.ride_complete, name="ride_complete"),
    path("rides/<int:pk>/passengers/<int:passenger_id>/arrived/", views.passenger_arrived, name="passenger_arrived"),
    path("rides/<int:pk>/join/", views.join_request_create, name="join_request"),
    path("rides/<int:pk>/joins/<int:join_id>/<str:action>/", views.join_request_decide, name="join_decide"),
    path("rides/<int:pk>/review/<str:action>/", views.ride_review, name="ride_review"),
    path("approvals/", views.approvals, name="approvals"),
    path("driver/", views.driver_portal, name="driver_portal"),
    path("driver/rides/<int:pk>/accept/", views.driver_accept_ride, name="driver_accept"),
    path("driver/rides/<int:pk>/decline/", views.driver_decline_ride, name="driver_decline"),
]
