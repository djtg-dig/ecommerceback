"""Technical API views."""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """Public, non-sensitive liveness endpoint."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers


HealthCheckView.get = extend_schema(
    tags=["Health"],
    operation_id="health_check",
    responses={200: inline_serializer("HealthResponse", {"status": serializers.CharField()})},
)(HealthCheckView.get)
