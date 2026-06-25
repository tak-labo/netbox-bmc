from netbox.api.routers import NetBoxRouter

from . import views

router = NetBoxRouter()
router.register("endpoints", views.BMCEndpointViewSet)
urlpatterns = router.urls
