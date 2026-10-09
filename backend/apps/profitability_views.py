from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business, BusinessMemberPermission
from apps.businesses.permissions import require_permission
from apps.profitability import build_profitability_summary
from apps.profitability_serializers import ProfitabilitySummarySerializer
from apps.reporting import resolve_reporting_period


class ProfitabilitySummaryView(APIView):
    """Expose the compact economic projection to authorized members."""

    http_method_names = ["get", "head", "options"]

    def get(self, request, business_public_id):
        business = Business.objects.filter(public_id=business_public_id).first()
        if business is None:
            return Response({"detail": "Not found."}, status=404)
        require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.VIEW_PROFITABILITY,
        )
        start, end = resolve_reporting_period(request.query_params)
        return Response(build_profitability_summary(business, start, end))


ProfitabilitySummaryView.get = extend_schema(
    tags=["Profitability"],
    operation_id="business_profitability_summary",
    parameters=[OpenApiParameter("period", str, required=False, enum=["today", "last_7_days", "last_30_days"]), OpenApiParameter("date_from", str, required=False), OpenApiParameter("date_to", str, required=False)],
    responses={
        200: ProfitabilitySummarySerializer,
        400: None,
        403: None,
        404: None,
    },
)(ProfitabilitySummaryView.get)
