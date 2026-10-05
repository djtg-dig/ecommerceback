from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView


def test_django_starts_and_health_is_public():
    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_drf_permission_rejects_anonymous_requests():
    class PrivateTestView(APIView):
        def get(self, request):
            return Response({"private": True})

    request = APIRequestFactory().get("/private/")
    response = PrivateTestView.as_view()(request)

    assert PrivateTestView.permission_classes == [IsAuthenticated]
    assert response.status_code in {401, 403}
