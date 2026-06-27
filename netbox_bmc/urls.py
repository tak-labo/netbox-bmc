from django.urls import path
from netbox.views.generic import ObjectChangeLogView, ObjectJobsView

from . import views
from .models import BMCEndpoint

urlpatterns = [
    path("endpoints/", views.BMCEndpointListView.as_view(), name="bmcendpoint_list"),
    path("endpoints/add/", views.BMCEndpointEditView.as_view(), name="bmcendpoint_add"),
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
    path("endpoints/<int:pk>/raw/", views.FetchRawView.as_view(), name="bmcendpoint_raw"),
]
