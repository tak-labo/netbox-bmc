from django.urls import path
from netbox.views.generic import ObjectChangeLogView, ObjectJobsView

from . import views
from .models import BMCEndpoint

urlpatterns = [
    path("endpoints/", views.BMCEndpointListView.as_view(), name="bmcendpoint_list"),
    path("endpoints/add/", views.BMCEndpointEditView.as_view(), name="bmcendpoint_add"),
    path("endpoints/test-connection/", views.ConnectivityTestView.as_view(),
         name="bmcendpoint_test_connection"),
    path("endpoints/<int:pk>/", views.BMCEndpointView.as_view(), name="bmcendpoint"),
    path("endpoints/<int:pk>/edit/", views.BMCEndpointEditView.as_view(), name="bmcendpoint_edit"),
    path("endpoints/<int:pk>/delete/", views.BMCEndpointDeleteView.as_view(), name="bmcendpoint_delete"),
    path("endpoints/<int:pk>/build-modules/", views.BuildModulesView.as_view(),
         name="bmcendpoint_build_modules"),
    path("endpoints/<int:pk>/build-modules/preview/", views.BuildModulesPreviewView.as_view(),
         name="bmcendpoint_build_modules_preview"),
    path("endpoints/<int:pk>/build-modules/apply/", views.BuildModulesApplyView.as_view(),
         name="bmcendpoint_build_modules_apply"),
    path("endpoints/<int:pk>/changelog/", ObjectChangeLogView.as_view(),
         name="bmcendpoint_changelog", kwargs={"model": BMCEndpoint}),
    path("endpoints/<int:pk>/jobs/", ObjectJobsView.as_view(),
         name="bmcendpoint_jobs", kwargs={"model": BMCEndpoint}),
    path("endpoints/<int:pk>/power/", views.PowerActionView.as_view(), name="bmcendpoint_power"),
    path("endpoints/<int:pk>/identify/", views.IdentifyActionView.as_view(), name="bmcendpoint_identify"),
    path("endpoints/<int:pk>/power-status/", views.PowerStatusView.as_view(), name="bmcendpoint_power_status"),
    path("endpoints/<int:pk>/network-sync/", views.NetworkSyncActionView.as_view(), name="bmcendpoint_network_sync"),
    path("endpoints/<int:pk>/manager-health-sync/", views.ManagerHealthSyncActionView.as_view(),
         name="bmcendpoint_manager_health_sync"),
    path("endpoints/<int:pk>/sensors-sync/", views.SensorsSyncActionView.as_view(), name="bmcendpoint_sensors_sync"),
    path("endpoints/<int:pk>/event-log-sync/", views.EventLogSyncActionView.as_view(),
         name="bmcendpoint_event_log_sync"),
    path("endpoints/<int:pk>/raw/", views.FetchRawView.as_view(), name="bmcendpoint_raw"),
]
