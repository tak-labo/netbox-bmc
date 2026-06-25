from netbox.api.viewsets import NetBoxModelViewSet

from ..models import BMCEndpoint
from .serializers import BMCEndpointSerializer


class BMCEndpointViewSet(NetBoxModelViewSet):
    queryset = BMCEndpoint.objects.prefetch_related("tags")
    serializer_class = BMCEndpointSerializer
